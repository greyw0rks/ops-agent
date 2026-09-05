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
        response = control.list_foundation_models(byProvider="anthropic")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("AccessDeniedException", "UnauthorizedOperation"):
            fail(
                f"Bedrock refused this identity in {region}: {code}",
                "The identity needs bedrock:ListFoundationModels and",
                "bedrock:InvokeModelWithResponseStream. Attach AmazonBedrockFullAccess",
                "or an equivalent inline policy.",
            )
        fail(f"Bedrock call failed in {region}: {exc}")
    except NoRegionError:
        fail("No region set.", "Set OPS_AWS_REGION or AWS_REGION.")

    models = response.get("modelSummaries", [])
    line(OK, f"bedrock reachable in {region}", f"{len(models)} Anthropic model(s) listed")
    return models


def show_models(models: list[dict]) -> None:
    """Print what is actually available, newest-looking first."""
    print()
    print(f"  {BOLD}Anthropic models visible to this account{RESET}")
    for model in sorted(models, key=lambda m: m["modelId"], reverse=True):
        streaming = "stream" if model.get("responseStreamingSupported") else f"{GREY}no-stream{RESET}"
        inference = ",".join(model.get("inferenceTypesSupported", []))
        print(f"    {model['modelId']:<58} {streaming:<12} {GREY}{inference}{RESET}")
    print()
    print(f"  {GREY}Cross-region inference profiles are prefixed us. / eu. / apac.{RESET}")
    print(f"  {GREY}Those are usually what you want for Sonnet — set OPS_BEDROCK_MODEL_ID.{RESET}")
    print()


def check_model_enabled(models: list[dict], model_id: str) -> None:
    """Step 4: is the configured model one this account can actually use?"""
    ids = {m["modelId"] for m in models}
    if model_id in ids:
        line(OK, "configured model is listed", model_id)
        return

    # Inference-profile ids (us.anthropic.…) are not returned by
    # list_foundation_models; they wrap a base model that is.
    base = model_id.split(".", 1)[1] if model_id.split(".", 1)[0] in ("us", "eu", "apac") else None
    if base and base in ids:
        line(OK, "configured model is a cross-region profile", f"{model_id} → {base}")
        return

    line(WARN, "configured model was not in the list", model_id)
    print(f"    {GREY}Run with --list to see what is available, then set OPS_BEDROCK_MODEL_ID.{RESET}")
    print(f"    {GREY}A model can also be listed but not enabled — --invoke is the real test.{RESET}")


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show every Anthropic model available")
    parser.add_argument("--invoke", action="store_true", help="send a real request (costs a few tokens)")
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
        show_models(models)

    check_model_enabled(models, model_id)

    if args.invoke:
        check_invoke(session, region, model_id)
    else:
        print()
        print(f"  {GREY}Add --invoke to prove it end to end (sends one real request).{RESET}")

    print()
    if settings.model_provider.lower() != "bedrock":
        print(
            f"  {WARN} OPS_MODEL_PROVIDER is {settings.model_provider!r}"
            " — set it to 'bedrock' to use this."
        )
        print()


if __name__ == "__main__":
    main()
