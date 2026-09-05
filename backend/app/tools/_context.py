"""Ambient run context for tools.

Tools are called by the model, so they cannot be handed a business id as an
argument — the model would be able to change it. Instead the runner binds the
context for the duration of a run and the tools read it from here. This is also
what keeps `business_id` out of every tool signature the model sees.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ApprovalStatus
from app.db.models import Approval


@dataclass
class RunContext:
    business_id: str
    run_id: str
    trigger: str
    # Set when the triggering event was a customer message.
    conversation_id: str | None = None
    customer_id: str | None = None
    # Escalations raised during this run, keyed by tool_use_id.
    escalations: dict[str, "PendingEscalation"] = field(default_factory=dict)


@dataclass
class PendingEscalation:
    """What the gate stashed when it paused a tool call for approval.

    The Strands interrupt id is only known after the handler returns, so the
    runner matches these up by tool_use_id once the agent comes back paused.
    """

    tool_name: str
    tool_use_id: str
    tool_input: dict
    title: str
    reason: str
    recommended_action: str
    policy_basis: str | None
    risk_level: str
    amount: float | None
    evidence: list


_current: ContextVar[RunContext | None] = ContextVar("ops_agent_run_context", default=None)


def current() -> RunContext:
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError("no agent run context bound — tools must be called inside a run")
    return ctx


def current_or_none() -> RunContext | None:
    return _current.get()


@contextmanager
def bind(ctx: RunContext):
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def approval_for(db: Session, run_id: str, action_type: str) -> Approval | None:
    """The approved decision authorising this action on this run, if any.

    Tools use this to stamp `approval_id` onto the record they write, so the audit
    trail shows which human decision let the action through.
    """
    return db.scalars(
        select(Approval)
        .where(
            Approval.run_id == run_id,
            Approval.action_type == action_type,
            Approval.status == ApprovalStatus.APPROVED,
        )
        .order_by(Approval.decided_at.desc())
    ).first()
