"""FastAPI application.

The API is the owner's side of the system: it configures the business, shows what
the agent has done, and is where approvals are granted. The agent itself is woken
by events rather than by requests.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.model import describe_model
from app.agent.registry import tool_names
from app.api.routes import approvals, dashboard, events
from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("app")

app = FastAPI(
    title="Ops Agent",
    version="0.1.0",
    description="An autonomous operations agent for small service businesses, built with Strands.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router)
app.include_router(approvals.router)
app.include_router(dashboard.router)


@app.on_event("startup")
def on_startup() -> None:
    model = describe_model()
    logger.info("ops-agent starting | model=%s/%s", model["provider"], model["model_id"])
    logger.info("tools registered: %d", len(tool_names()))
    if not settings.api_token:
        logger.warning(
            "OPS_API_TOKEN is not set — the API is unauthenticated. Fine for a local demo; "
            "set it before exposing this to a network."
        )


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "agent": describe_model(),
        "tools": len(tool_names()),
        "authenticated": bool(settings.api_token),
    }
