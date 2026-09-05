"""Check whether this machine can actually run the agent on Amazon Bedrock.

Bedrock fails in four distinct ways that all look like "it doesn't work", so this
checks them one at a time and says which one you have:

    1. no credentials on the machine
    2. credentials that don't resolve to an identity
    3. an identity without Bedrock permissions
    4. Bedrock reachable, but the configured model is not enabled in this region

Usage:
    python -m scripts.preflight_bedrock
    python -m scripts.preflight_bedrock --list      # every Anthropic model available
    python -m scripts.preflight_bedrock --invoke    # actually spend a few tokens
"""

import argparse
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, NoRegionError

from app.config import settings

GREEN, RED, YELLOW, GREY, BOLD, RESET = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[90m",
    "\033[1m",
    "\033[0m",
)
OK, FAIL, WARN = f"{GREEN}✓{RESET}", f"{RED}✗{RESET}", f"{YELLOW}!{RESET}"


def line(mark: str, label: str, detail: str = "") -> None:
    print(f"  {mark} {label}" + (f"  {GREY}{detail}{RESET}" if detail else ""))


def fail(message: str, *fixes: str) -> None:
    print()
    print(f"  {RED}{BOLD}{message}{RESET}")
    for fix in fixes:
        print(f"    {fix}")
    print()
    sys.exit(1)


def check_credentials(region: str):
    """Step 1 and 2: are there credentials, and do they resolve to an identity?"""
    session = boto3.Session(region_name=region)
    creds = session.get_credentials()
    if creds is None:
        fail(
            "No AWS credentials found.",
            "aws configure                      # access key + secret",
            "aws configure sso                  # IAM Identity Center",
            "or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY",
        )
    line(OK, "credentials found", f"via {creds.method}")

    try:
        identity = session.client("sts").get_caller_identity()
    except (ClientError, BotoCoreError) as exc:
        fail(
            f"Credentials did not resolve to an identity: {exc}",
            "Check the key is active and not from a deleted user:",
            "  aws sts get-caller-identity",
        )
    line(OK, "identity", identity["Arn"])
    line(OK, "account", identity["Account"])
    return session


def check_bedrock(session, region: str) -> list[dict]:
    """Step 3: does this identity have Bedrock access in this region?"""
    control = session.client("bedrock", region_name=region)
    try:
        response = control.list_foundation_models()
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("AccessDeniedException", "UnauthorizedOperation"):
            fail(
                f"Bedrock refused this identity in {region}: {code}",
                "The identity needs bedrock:ListFoundationModels and",
                "bedrock:InvokeModelWithResponseStream. Attach the policy in",
                "infrastructure/aws/bedrock-invoke-policy.json.",
            )
        fail(f"Bedrock call failed in {region}: {exc}")
    except NoRegionError:
        fail("No region set.", "Set OPS_AWS_REGION or AWS_REGION.")

    models = [m for m in response.get("modelSummaries", []) if "TEXT" in m.get("outputModalities", [])]
    line(OK, f"bedrock reachable in {region}", f"{len(models)} text model(s) listed")
    return models


def show_models(session, models: list[dict], region: str) -> None:
    """Print what is actually invokable.

    `list_foundation_models` is misleading on its own: most current models are
    `INFERENCE_PROFILE` only, so the id you can actually pass is the profile id, not
    the model id. This lists the profiles, which is the answer to "what do I put in
    OPS_BEDROCK_MODEL_ID".
    """
    print()
    print(f"  {BOLD}Invokable inference profiles in {region}{RESET}")
    control = session.client("bedrock", region_name=region)
    try:
        profiles: list[dict] = []
        for page in control.get_paginator("list_inference_profiles").paginate(
            typeEquals="SYSTEM_DEFINED"
        ):
            profiles += page.get("inferenceProfileSummaries", [])
    except ClientError as exc:
        line(WARN, "could not list inference profiles", str(exc))
        profiles = []

    for profile in sorted(profiles, key=lambda p: p["inferenceProfileId"]):
        if profile.get("status") != "ACTIVE":
            continue
        print(f"    {profile['inferenceProfileId']}")

    on_demand = [
        m["modelId"] for m in models if "ON_DEMAND" in m.get("inferenceTypesSupported", [])
    ]
    if on_demand:
        print()
        print(f"  {BOLD}Also invokable directly (ON_DEMAND){RESET}")
        for model_id in sorted(on_demand):
            print(f"    {model_id}")
    print()


def check_model_enabled(models: list[dict], model_id: str) -> None:
    """Is the configured model one this account can see at all?"""
    ids = {m["modelId"] for m in models}
    if model_id in ids:
        line(OK, "configured model is listed", model_id)
        return

    # Inference-profile ids (us./eu./apac./global.) wrap a base model that is listed.
    prefix, _, base = model_id.partition(".")
    if prefix in ("us", "eu", "apac", "global") and base in ids:
        line(OK, "configured model is a cross-region profile", f"{model_id} → {base}")
        return

    line(WARN, "configured model was not in the list", model_id)
    print(f"    {GREY}Run with --list to see what is invokable, then set OPS_BEDROCK_MODEL_ID.{RESET}")


TOOL_PROBE = {
    "tools": [
        {
            "toolSpec": {
                "name": "check_availability",
                "description": "Check available appointment slots for a service on a date.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "service_id": {"type": "string"},
                            "date": {"type": "string", "description": "YYYY-MM-DD"},
                        },
                        "required": ["service_id", "date"],
                    }
                },
            }
        }
    ]
}


def probe_tools(session, region: str, model_ids: list[str]) -> None:
    """Check that a candidate model actually calls a tool rather than describing one.

    This is the only capability the agent genuinely requires. A model that answers in
    prose instead of emitting a toolUse block is unusable here regardless of how it
    scores on anything else.
    """
    runtime = session.client("bedrock-runtime", region_name=region)
    print()
    print(f"  {BOLD}Tool-use probe{RESET}  {GREY}one call each{RESET}")
    for model_id in model_ids:
        try:
            response = runtime.converse(
                modelId=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": "Is svc_1 free on 2026-09-12? Check availability."}],
                    }
                ],
                toolConfig=TOOL_PROBE,
                inferenceConfig={"maxTokens": 512, "temperature": 0},
            )
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            message = exc.response["Error"].get("Message", "")[:64]
            print(f"    {FAIL} {model_id:<46} {GREY}{code}: {message}{RESET}")
            continue

        called = [
            block["toolUse"]["name"]
            for block in response["output"]["message"]["content"]
            if "toolUse" in block
        ]
        usage = response.get("usage", {})
        if called:
            print(
                f"    {OK} {model_id:<46} called {called} "
                f"{GREY}({usage.get('inputTokens')}in/{usage.get('outputTokens')}out){RESET}"
            )
        else:
            print(f"    {WARN} {model_id:<46} {GREY}answered in prose, no tool call{RESET}")


def check_invoke(session, region: str, model_id: str) -> None:
    """The only check that proves it works: send a real request."""
    runtime = session.client("bedrock-runtime", region_name=region)
    try:
        response = runtime.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "Reply with the single word: ready"}]}],
            inferenceConfig={"maxTokens": 16, "temperature": 0},
        )
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        message = exc.response["Error"].get("Message", "")
        if code == "AccessDeniedException":
            fail(
                f"Model access is not enabled for {model_id} in {region}.",
                "Bedrock console → Model access → Manage model access → enable the",
                "Anthropic models, then wait for the status to become 'Access granted'.",
                f"{GREY}{message}{RESET}",
            )
        if code == "ValidationException":
            fail(
                f"Bedrock rejected the model id {model_id!r}.",
                "Run with --list and copy an id from there.",
                f"{GREY}{message}{RESET}",
            )
        if code == "ThrottlingException":
            fail(
                "Throttled on the first call — the account has no Bedrock quota yet.",
                "New accounts sometimes need a quota increase for on-demand inference.",
            )
        fail(f"Invoke failed: {code} — {message}")

    text = response["output"]["message"]["content"][0]["text"].strip()
    usage = response.get("usage", {})
    line(OK, "invoke succeeded", f"{text!r} ({usage.get('inputTokens')}in/{usage.get('outputTokens')}out)")


#: Models worth considering for this agent, strongest all-AWS story first. Probed with
#: --tools so the choice is made on what a model does, not on what it claims. Anthropic
#: and OpenAI are omitted deliberately: both refuse requests from countries their
#: providers do not serve, independently of AWS, so they are not portable choices here.
TOOL_CANDIDATES = [
    "us.amazon.nova-premier-v1:0",
    "us.amazon.nova-pro-v1:0",
    "us.amazon.nova-2-lite-v1:0",
    "us.meta.llama4-maverick-17b-instruct-v1:0",
    "us.mistral.pixtral-large-2502-v1:0",
    "us.xai.grok-4.6",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show every invokable model id")
    parser.add_argument("--invoke", action="store_true", help="send a real request (costs a few tokens)")
    parser.add_argument("--tools", action="store_true", help="probe candidates for real tool use")
    parser.add_argument("--region", help="override OPS_AWS_REGION for this check")
    parser.add_argument("--model", help="override OPS_BEDROCK_MODEL_ID for this check")
    args = parser.parse_args()

    region = args.region or settings.aws_region
    model_id = args.model or settings.bedrock_model_id

    print()
    print(f"{BOLD}Bedrock preflight{RESET}  {GREY}region={region} model={model_id}{RESET}")
    print()

    try:
        session = check_credentials(region)
        models = check_bedrock(session, region)
    except NoCredentialsError:
        fail("No AWS credentials found.", "aws configure")

    if args.list:
        show_models(session, models, region)

    check_model_enabled(models, model_id)

    if args.tools:
        probe_tools(session, region, [model_id, *(m for m in TOOL_CANDIDATES if m != model_id)])

    if args.invoke:
        check_invoke(session, region, model_id)
    elif not args.tools:
        print()
        print(f"  {GREY}Add --invoke to prove it end to end, or --tools to compare models.{RESET}")

    print()
    if settings.model_provider.lower() != "bedrock":
        print(
            f"  {WARN} OPS_MODEL_PROVIDER is {settings.model_provider!r}"
            " — set it to 'bedrock' to use this."
        )
        print()


if __name__ == "__main__":
    main()
