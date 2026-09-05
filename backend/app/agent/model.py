"""Model provider selection.

Amazon Bedrock is the intended runtime — it is what the AgentCore deployment uses
and what `MODEL_PROVIDER=bedrock` selects. The Anthropic-compatible path exists so
the whole system can be developed and demonstrated without Bedrock access; it
speaks the same tool-use protocol, so nothing else in the codebase changes.
"""

import logging

from strands.models import BedrockModel
from strands.models.model import Model

from app.config import settings

logger = logging.getLogger(__name__)


def build_model() -> Model:
    """Construct the model the agent will reason with."""
    provider = (settings.model_provider or "bedrock").strip().lower()

    if provider == "bedrock":
        logger.info("model provider=bedrock model_id=%s", settings.bedrock_model_id)
        return BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.aws_region,
            max_tokens=settings.model_max_tokens,
            temperature=0.2,
        )

    if provider == "anthropic":
        from strands.models.anthropic import AnthropicModel

        if not settings.compat_api_key:
            raise RuntimeError("OPS_MODEL_PROVIDER=anthropic requires OPS_COMPAT_API_KEY")

        client_args: dict = {"api_key": settings.compat_api_key}
        if settings.compat_base_url:
            client_args["base_url"] = settings.compat_base_url

        logger.info(
            "model provider=anthropic-compatible model_id=%s base_url=%s",
            settings.compat_model_id,
            settings.compat_base_url or "default",
        )
        return AnthropicModel(
            client_args=client_args,
            model_id=settings.compat_model_id,
            max_tokens=settings.model_max_tokens,
            params={"temperature": 0.2},
        )

    raise RuntimeError(f"unknown OPS_MODEL_PROVIDER {provider!r} (expected 'bedrock' or 'anthropic')")


def describe_model() -> dict:
    provider = (settings.model_provider or "bedrock").strip().lower()
    return {
        "provider": provider,
        "model_id": settings.bedrock_model_id if provider == "bedrock" else settings.compat_model_id,
        "region": settings.aws_region if provider == "bedrock" else None,
        "max_tokens": settings.model_max_tokens,
    }
