"""Agent accountability records.

These three tables are what turns an LLM loop into something a business owner can
audit: every run, every tool call, and every decision that was escalated.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.enums import ActionStatus, ApprovalStatus, RiskLevel, RunStatus
from app.db.ids import id_factory


class AgentRun(Base, TimestampMixin):
    """One wake-up of the agent, from triggering event to final state."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("agent_run"))
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True, nullable=False)

    trigger: Mapped[str] = mapped_column(String(48), nullable=False)
    # Whatever the event pointed at: a conversation id, a task id, a document key.
    trigger_ref: Mapped[str | None] = mapped_column(String(64), index=True)
    trigger_payload: Mapped[dict] = mapped_column(JSON, default=dict)

    # What the agent decided the event was about. Filled in after the run.
    intent: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default=RunStatus.RUNNING, index=True)

    # Strands session id — this is what makes a paused run resumable.
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    actions: Mapped[list["AgentAction"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentAction.sequence"
    )
    approvals: Mapped[list["Approval"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class AgentAction(Base, TimestampMixin):
    """One tool call, with what the policy engine decided about it."""

    __tablename__ = "agent_actions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("agent_action"))
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_use_id: Mapped[str | None] = mapped_column(String(80), index=True)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(24), default=ActionStatus.SUCCESS)
    risk_level: Mapped[str] = mapped_column(String(8), default=RiskLevel.LOW)
    # What the policy engine said: allow / require_approval / deny.
    policy_decision: Mapped[str] = mapped_column(String(24), default="allow")
    policy_reason: Mapped[str | None] = mapped_column(Text)
    approval_id: Mapped[str | None] = mapped_column(String(32), index=True)

    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    run: Mapped[AgentRun] = relationship(back_populates="actions")


class Approval(Base, TimestampMixin):
    """A decision the agent handed back to a human.

    `interrupt_id` is the Strands interrupt this row corresponds to. Resolving the
    approval resumes the paused run with that id, so the agent picks up exactly
    where it stopped rather than starting over.
    """

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("approval"))
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True, nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True, nullable=False)
    interrupt_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(8), default=RiskLevel.HIGH)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Why the agent thinks this should happen, in the owner's language.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    # Which policy clause forced the escalation.
    policy_basis: Mapped[str | None] = mapped_column(Text)

    amount: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(8))

    # Records the owner can click through to: bookings, conversations, history.
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    # The exact tool call that will run on approval.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(16), default=ApprovalStatus.PENDING, index=True)
    decided_by: Mapped[str | None] = mapped_column(String(80))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)

    run: Mapped[AgentRun] = relationship(back_populates="approvals")
