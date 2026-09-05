# AWS setup

What the agent needs from AWS, and how to prove it has it.

## Permissions

[`bedrock-invoke-policy.json`](bedrock-invoke-policy.json) is the policy this agent
runs on: invoke any Bedrock foundation model, and list them so the preflight can report
what your account can actually see. `AmazonBedrockFullAccess` also works and is quicker
to attach.

Three details that are easy to get wrong, each of which cost a debugging cycle here:

**Grant both resource ARNs.** A model id like `us.amazon.nova-pro-v1:0` is a
cross-region *inference profile* that routes to the underlying foundation model in
whichever region has capacity. Bedrock authorises against **both** the
`inference-profile/*` ARN and the `foundation-model/*` ARNs it routes to. Granting only
one of the two fails.

**Do not scope `foundation-model` to a single provider.** An earlier version of this
policy allowed only `foundation-model/anthropic.*`. Every non-Anthropic model then
failed with `ValidationException: Operation not allowed` — which reads like a model
availability problem, not a permissions problem, because Bedrock does not always
surface an under-granted resource as `AccessDenied`.

**`foundation-model` ARNs have no account id.** `arn:aws:bedrock:*::foundation-model/…`
with the empty segment is correct: the models are not yours.

```bash
aws iam create-policy \
  --policy-name OpsAgentBedrockInvoke \
  --policy-document file://infrastructure/aws/bedrock-invoke-policy.json
```

If you later move paused-run storage to S3 (`OPS_AGENT_SESSION_S3_BUCKET`), add
`s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` and `s3:ListBucket` on
`arn:aws:s3:::<bucket>/ops-agent/sessions/*`.

## Model access is no longer a manual step

The Bedrock **Model access** page has been retired. Serverless foundation models are
enabled automatically on first invocation in your account. Two carve-outs remain:

- **Anthropic models** may ask a first-time user to submit use-case details.
- **Marketplace-served models** need one invocation by a principal that holds AWS
  Marketplace permissions before they are enabled account-wide.

## Anthropic models are geo-restricted, independently of AWS

Bedrock will refuse Anthropic models outright from a country Anthropic does not serve:

```
ValidationException: Access to Anthropic models is not allowed from unsupported
countries, regions, or territories.
```

This is not an IAM problem, a region problem, or a model-access problem, and no
configuration changes it — see
[anthropic.com/supported-countries](https://www.anthropic.com/supported-countries).
The response is to pick a different Bedrock model, which is a one-variable change
(`OPS_BEDROCK_MODEL_ID`), because nothing above `app/agent/model.py` knows which model
it is talking to.

## Prove it

```bash
make preflight
```

Runs [`backend/scripts/preflight_bedrock.py`](../../backend/scripts/preflight_bedrock.py),
which separates the failures that all otherwise present as "it doesn't work":
credentials present, credentials resolve to an identity, identity may call Bedrock,
model reachable from here.

```
Bedrock preflight  region=us-west-2 model=us.amazon.nova-pro-v1:0

  ✓ credentials found            via shared-credentials-file
  ✓ identity                     arn:aws:iam::…:user/ops-agent
  ✓ bedrock reachable in us-west-2
  ✓ invoke succeeded             'ready' (18in/3out)
```

`--list` prints every model the account can see, and `--tools` checks that a candidate
actually returns a tool call rather than describing one — which is the only property
this agent needs from a model.

## Region

`us-west-2` and `us-east-1` carry the widest selection. The preflight lists what is
actually there, so choose after looking rather than before.
