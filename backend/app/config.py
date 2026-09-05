"""Application configuration.

All runtime configuration lives here so that the agent, the API and the scripts
share one source of truth. Values are read from the environment (and from a
`.env` file at the repository root during local development).
"""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]

# dotenv does not override variables that are already set in the environment,
# which is what we want: real deployment env vars win over the local .env file.
load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_ROOT / ".env")


class Settings(BaseSettings):
    """Typed settings for the whole backend.

    Every variable is read under the `OPS_` prefix. That is deliberate: bare names
    like `ANTHROPIC_API_KEY` and `AWS_REGION` are commonly already exported in a
    developer's shell for some other tool, and an ambient value silently winning
    over the project's own `.env` is a genuinely hard bug to see — the agent keeps
    working, it just talks to the wrong endpoint.
    """

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, env_prefix="OPS_")

    # --- database ---
    database_url: str = "postgresql+psycopg://opsagent:opsagent@localhost:5437/opsagent"

    # --- model provider ---
    # "bedrock" for Amazon Bedrock (production / AgentCore), "anthropic" for any
    # Anthropic-compatible endpoint (local development).
    model_provider: str = "bedrock"

    # Region for Bedrock. Falls back to the conventional AWS variables, since
    # those are set by the environment rather than by this project.
    aws_region: str = Field(
        default="us-west-2",
        validation_alias=AliasChoices("OPS_AWS_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"),
    )
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

    # Anthropic-compatible endpoint, used when model_provider == "anthropic".
    compat_api_key: str = ""
    compat_base_url: str = ""
    compat_model_id: str = "claude-sonnet-4-5-20250929"

    model_max_tokens: int = 4096

    # --- agent runtime ---
    agent_session_dir: str = ".sessions"
    agent_session_s3_bucket: str = ""

    # --- api ---
    api_host: str = "0.0.0.0"
    api_port: int = 8010
    # The dashboard dev server runs on 3010; 3000 is included because it is what a
    # bare `next dev` picks and someone will inevitably run it that way.
    cors_origins: str = "http://localhost:3010,http://localhost:3000"
    log_level: str = "INFO"
    # Shared secret for the owner-facing API. When empty the API is unauthenticated,
    # which is fine for a local demo and not fine anywhere else — `main.py` warns
    # loudly at startup if it is unset.
    api_token: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def session_dir_path(self) -> Path:
        path = Path(self.agent_session_dir)
        return path if path.is_absolute() else BACKEND_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
