# AWS setup

What the agent needs from AWS, and how to prove it has it.

## Least privilege

[`bedrock-invoke-policy.json`](bedrock-invoke-policy.json) is the smallest policy that
runs this agent: invoke Anthropic models, and list them so the preflight can tell you
which ones your account can see.

Two details in it that are easy to get wrong:

- **Both resource ARNs are needed for cross-region inference profiles.** A model id like
  `us.anthropic.claude-sonnet-4-5-20250929-v1:0` is an inference profile that routes to
  the underlying foundation model in whichever region has capacity. Granting only
  `inference-profile/*` fails at the routing step; granting only `foundation-model/*`
  fails at the profile.
- **`foundation-model` ARNs have no account id** — `arn:aws:bedrock:*::foundation-model/…`
  with the empty segment is correct, because the models are not yours.

`AmazonBedrockFullAccess` also works and is quicker to attach. Use it if you are in a
hurry; use this if you would rather the hackathon judges see a scoped policy.

```bash
aws iam create-policy \
  --policy-name OpsAgentBedrockInvoke \
  --policy-document file://infrastructure/aws/bedrock-invoke-policy.json
```

If you later switch paused-run storage from local disk to S3
(`OPS_AGENT_SESSION_S3_BUCKET`), add `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`
and `s3:ListBucket` on `arn:aws:s3:::<bucket>/ops-agent/sessions/*`.

## Model access is a separate step

IAM permission to call Bedrock is not the same thing as your account being allowed to
use a particular model. Anthropic models have to be enabled per region:

> Bedrock console → **Model access** → Manage model access → tick the Anthropic models
> → Save changes, then wait for **Access granted**.

Until that is done, `bedrock:InvokeModel` returns `AccessDeniedException` even with a
correct policy — which reads like a permissions problem and is not one.

## Prove it

```bash
make preflight
```

Runs [`backend/scripts/preflight_bedrock.py`](../../backend/scripts/preflight_bedrock.py),
which checks the four things that fail independently — credentials present, credentials
resolve to an identity, identity may call Bedrock, model actually enabled — and says
which one is wrong instead of reporting "it doesn't work".

```
Bedrock preflight  region=us-west-2 model=us.anthropic.claude-sonnet-4-5-20250929-v1:0

  ✓ credentials found            via shared-credentials-file
  ✓ identity                     arn:aws:iam::…:user/ops-agent
  ✓ account                      …
  ✓ bedrock reachable in us-west-2   9 Anthropic model(s) listed
  ✓ configured model is a cross-region profile
  ✓ invoke succeeded             'ready' (18in/3out)
```

`--list` prints every Anthropic model the account can see, which is how you find the
right value for `OPS_BEDROCK_MODEL_ID` rather than guessing at a version string.

## Region

`us-west-2` and `us-east-1` carry the widest Anthropic selection. The preflight lists
what is actually there, so pick after looking rather than before.
