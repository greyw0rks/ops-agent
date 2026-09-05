"""Agent construction.

The agent is assembled the same way for every run: the business's own context in
the system prompt, the full tool registry, the policy gate as an intervention, the
audit observer as a hook, and a session manager keyed to the run.

The session manager is what makes an approval workflow possible. A run that pauses
for a human is written to durable storage and rebuilt — possibly in a different
process, minutes or hours later — when the decision comes back.
"""

import logging

from strands import Agent
from strands.session import FileSessionManager, S3SessionManager, SessionManager

from app.agent.model import build_model
from app.agent.observer import RunObserver
from app.agent.prompts import system_prompt
from app.agent.registry import ALL_TOOLS
from app.config import settings
from app.policy.gate import PolicyGate

logger = logging.getLogger(__name__)


def build_session_manager(session_id: str) -> SessionManager:
    """Durable storage for a run's conversation and interrupt state."""
    if settings.agent_session_s3_bucket:
        return S3SessionManager(
            session_id=session_id,
            bucket=settings.agent_session_s3_bucket,
            prefix="ops-agent/sessions",
            region_name=settings.aws_region,
        )

    directory = settings.session_dir_path
    directory.mkdir(parents=True, exist_ok=True)
    return FileSessionManager(session_id=session_id, storage_dir=str(directory))


def build_agent(snapshot: dict, session_id: str) -> Agent:
    """Build the operations agent for one run."""
    return Agent(
        model=build_model(),
        tools=ALL_TOOLS,
        system_prompt=system_prompt(snapshot),
        interventions=[PolicyGate()],
        hooks=[RunObserver()],
        session_manager=build_session_manager(session_id),
        callback_handler=None,
        name="ops-agent",
        description="Operations agent for a small service business",
    )
