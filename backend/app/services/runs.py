"""Agent run and action bookkeeping.

Nothing here is optional decoration: the run record is what lets a paused agent
be resumed, and the action records are what the owner reads instead of taking the
agent's word for what it did.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import ActionStatus, PolicyDecision, RiskLevel, RunStatus
from app.db.ids import new_id
from app.db.models import AgentAction, AgentRun
from app.services.business import get_business
from app.services.common import local_iso


def start_run(
    db: Session,
    business_id: str,
    trigger: str,
    trigger_ref: str | None = None,
    trigger_payload: dict | None = None,
) -> AgentRun:
    """Open a run. The session id is the handle Strands uses to resume it."""
    run_id = new_id("agent_run")
    run = AgentRun(
        id=run_id,
        business_id=business_id,
        trigger=trigger,
        trigger_ref=trigger_ref,
        trigger_payload=trigger_payload or {},
        status=RunStatus.RUNNING,
        session_id=f"ops-{run_id}",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    return run


def next_sequence(db: Session, run_id: str) -> int:
    """Next position in the run's action log.

    Strands executes a turn's tool calls concurrently and each one records itself in
    its own transaction, so `max(sequence) + 1` on its own will hand the same number
    to two actions. Locking the run row first serialises the numbering per run,
    which is cheap because a run's tool calls are the only contenders for it.
    """
    db.execute(select(AgentRun.id).where(AgentRun.id == run_id).with_for_update())
    current = db.scalar(select(func.max(AgentAction.sequence)).where(AgentAction.run_id == run_id))
    return (current or 0) + 1


def record_action(
    db: Session,
    run_id: str,
    tool: str,
    tool_input: dict | None = None,
    output: dict | None = None,
    status: str = ActionStatus.SUCCESS,
    risk_level: str = RiskLevel.LOW,
    policy_decision: str = PolicyDecision.ALLOW,
    policy_reason: str | None = None,
    approval_id: str | None = None,
    tool_use_id: str | None = None,
    latency_ms: int = 0,
) -> AgentAction:
    action = AgentAction(
        run_id=run_id,
        sequence=next_sequence(db, run_id),
        tool=tool,
        tool_use_id=tool_use_id,
        input=_jsonable(tool_input or {}),
        output=_jsonable(output or {}),
        status=status,
        risk_level=risk_level,
        policy_decision=policy_decision,
        policy_reason=policy_reason,
        approval_id=approval_id,
        latency_ms=latency_ms,
    )
    db.add(action)
    db.flush()
    return action


def _jsonable(value):
    """Best-effort conversion so an odd tool argument cannot break the audit write."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def mark_awaiting_approval(db: Session, run_id: str) -> None:
    run = db.get(AgentRun, run_id)
    if run:
        run.status = RunStatus.AWAITING_APPROVAL
        db.flush()


def mark_running(db: Session, run_id: str) -> None:
    run = db.get(AgentRun, run_id)
    if run:
        run.status = RunStatus.RUNNING
        db.flush()


def complete_run(
    db: Session,
    run_id: str,
    summary: str | None = None,
    intent: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> AgentRun | None:
    run = db.get(AgentRun, run_id)
    if run is None:
        return None
    run.status = RunStatus.COMPLETED
    run.completed_at = datetime.now(UTC)
    run.summary = summary
    if intent:
        run.intent = intent
    run.input_tokens = (run.input_tokens or 0) + input_tokens
    run.output_tokens = (run.output_tokens or 0) + output_tokens
    run.duration_ms = int((run.completed_at - run.started_at).total_seconds() * 1000)
    db.flush()
    return run


def fail_run(db: Session, run_id: str, error: str) -> None:
    run = db.get(AgentRun, run_id)
    if run:
        run.status = RunStatus.FAILED
        run.error = error[:4000]
        run.completed_at = datetime.now(UTC)
        run.duration_ms = int((run.completed_at - run.started_at).total_seconds() * 1000)
        db.flush()


def set_intent(db: Session, run_id: str, intent: str) -> None:
    run = db.get(AgentRun, run_id)
    if run and not run.intent:
        run.intent = intent
        db.flush()


def action_dict(action: AgentAction, tz: str) -> dict:
    return {
        "action_id": action.id,
        "sequence": action.sequence,
        "tool": action.tool,
        "input": action.input,
        "output": action.output,
        "status": action.status,
        "risk_level": action.risk_level,
        "policy_decision": action.policy_decision,
        "policy_reason": action.policy_reason,
        "approval_id": action.approval_id,
        "latency_ms": action.latency_ms,
        "at": local_iso(action.created_at, tz),
    }


def run_dict(run: AgentRun, tz: str, include_actions: bool = False) -> dict:
    payload = {
        "run_id": run.id,
        "trigger": run.trigger,
        "trigger_ref": run.trigger_ref,
        "intent": run.intent,
        "status": run.status,
        "summary": run.summary,
        "error": run.error,
        "started_at": local_iso(run.started_at, tz),
        "completed_at": local_iso(run.completed_at, tz),
        "duration_ms": run.duration_ms,
        "action_count": len(run.actions),
        "tokens": {"input": run.input_tokens, "output": run.output_tokens},
    }
    if include_actions:
        payload["actions"] = [action_dict(a, tz) for a in run.actions]
    return payload


def get_run(db: Session, business_id: str, run_id: str) -> dict | None:
    run = db.get(AgentRun, run_id)
    if run is None or run.business_id != business_id:
        return None
    tz = get_business(db, business_id).timezone
    return run_dict(run, tz, include_actions=True)


def list_runs(db: Session, business_id: str, limit: int = 30, status: str | None = None) -> list[dict]:
    stmt = select(AgentRun).where(AgentRun.business_id == business_id)
    if status:
        stmt = stmt.where(AgentRun.status == status)
    runs = db.scalars(stmt.order_by(AgentRun.started_at.desc()).limit(limit)).all()
    tz = get_business(db, business_id).timezone
    return [run_dict(r, tz, include_actions=True) for r in runs]


def get_run_row(db: Session, run_id: str) -> AgentRun | None:
    return db.get(AgentRun, run_id)
