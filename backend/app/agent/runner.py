"""The agent run lifecycle.

Every wake-up of the agent goes through here, and every wake-up follows the same
shape:

    event -> open a run -> load business context -> bind the run context
          -> invoke the agent -> either finish, or pause for a human
          -> record everything

`resume()` is the other half. When an approval is decided, the paused run is
rebuilt from its session and continued at the exact tool call that stopped it.
"""

import logging
from dataclasses import dataclass, field

from app.agent.context import business_snapshot
from app.agent.ops_agent import build_agent
from app.agent.prompts import event_brief
from app.db.enums import ApprovalStatus, RunStatus
from app.db.session import session_scope
from app.policy.gate import interrupt_id_for
from app.services import approvals as approval_service
from app.services import business as business_service
from app.services import runs as run_service
from app.tools import _context as run_context
from app.tools._context import RunContext

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    run_id: str
    status: str
    summary: str | None = None
    pending_approvals: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def paused(self) -> bool:
        return self.status == RunStatus.AWAITING_APPROVAL


def handle_event(
    trigger: str,
    business_id: str | None = None,
    trigger_ref: str | None = None,
    payload: dict | None = None,
) -> RunResult:
    """Wake the agent for one event and run it to completion or to a pause."""
    payload = payload or {}

    with session_scope() as db:
        business = (
            business_service.get_business(db, business_id)
            if business_id
            else business_service.get_default_business(db)
        )
        snapshot = business_snapshot(db, business)
        run = run_service.start_run(
            db,
            business_id=business.id,
            trigger=trigger,
            trigger_ref=trigger_ref,
            trigger_payload=payload,
        )
        run_id, session_id = run.id, run.session_id

    ctx = RunContext(
        business_id=snapshot["business_id"],
        run_id=run_id,
        trigger=trigger,
        conversation_id=payload.get("conversation_id"),
        customer_id=payload.get("customer_id"),
    )

    brief = event_brief(trigger, **payload)
    logger.info("run start id=%s trigger=%s ref=%s", run_id, trigger, trigger_ref)
    return _invoke(ctx, snapshot, session_id, brief)


def resume(run_id: str) -> RunResult:
    """Continue a paused run now that its decisions have been made."""
    with session_scope() as db:
        run = run_service.get_run_row(db, run_id)
        if run is None:
            return RunResult(run_id=run_id, status="not_found", error="unknown run")
        if run.status != RunStatus.AWAITING_APPROVAL:
            return RunResult(
                run_id=run_id,
                status=run.status,
                error=f"run is {run.status}, not awaiting approval",
            )

        approvals = [a for a in run.approvals if a.status != ApprovalStatus.PENDING]
        still_pending = [a for a in run.approvals if a.status == ApprovalStatus.PENDING]
        if not approvals:
            return RunResult(run_id=run_id, status=run.status, error="no decision has been made yet")
        if still_pending:
            return RunResult(
                run_id=run_id,
                status=run.status,
                error=f"{len(still_pending)} decision(s) on this run are still open",
            )

        business = business_service.get_business(db, run.business_id)
        snapshot = business_snapshot(db, business)
        session_id = run.session_id
        payload = run.trigger_payload or {}
        trigger = run.trigger

        responses = [
            {
                "interruptResponse": {
                    "interruptId": a.interrupt_id,
                    "response": "yes" if a.status == ApprovalStatus.APPROVED else "no",
                }
            }
            for a in approvals
        ]
        decided = approvals[-1]
        decision_text = "approved" if decided.status == ApprovalStatus.APPROVED else "rejected"

        run_service.mark_running(db, run_id)

    ctx = RunContext(
        business_id=snapshot["business_id"],
        run_id=run_id,
        trigger=trigger,
        conversation_id=payload.get("conversation_id"),
        customer_id=payload.get("customer_id"),
    )

    logger.info("run resume id=%s decision=%s", run_id, decision_text)
    return _invoke(ctx, snapshot, session_id, responses)


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


def _invoke(ctx: RunContext, snapshot: dict, session_id: str, agent_input) -> RunResult:
    """Run the agent with the run context bound, then record how it ended."""
    agent = build_agent(snapshot, session_id)

    try:
        with run_context.bind(ctx):
            result = agent(agent_input)
    except Exception as exc:  # noqa: BLE001 - a failed run must still be recorded
        detail = f"{type(exc).__name__}: {exc}"
        logger.exception("run failed id=%s", ctx.run_id)
        with session_scope() as db:
            run_service.fail_run(db, ctx.run_id, detail)
        return RunResult(run_id=ctx.run_id, status=RunStatus.FAILED, error=detail)

    if result.stop_reason == "interrupt":
        return _pause(ctx, result)
    return _finish(ctx, result)


def _pause(ctx: RunContext, result) -> RunResult:
    """The gate stopped the run. Make sure the owner's queue reflects it."""
    interrupts = list(result.interrupts or [])

    with session_scope() as db:
        for interrupt in interrupts:
            existing = approval_service.find_by_interrupt(db, ctx.run_id, interrupt.id)
            if existing is not None:
                continue
            # The gate should have written this already. If the interrupt id scheme
            # ever changes underneath us, recover from what the gate stashed rather
            # than losing the decision.
            _repair_approval(db, ctx, interrupt)

        run_service.mark_awaiting_approval(db, ctx.run_id)
        pending = approval_service.list_approvals(db, ctx.business_id, status=ApprovalStatus.PENDING)
        detail = run_service.get_run(db, ctx.business_id, ctx.run_id) or {}

    logger.info("run paused id=%s interrupts=%d", ctx.run_id, len(interrupts))
    return RunResult(
        run_id=ctx.run_id,
        status=RunStatus.AWAITING_APPROVAL,
        summary=detail.get("summary"),
        pending_approvals=[a for a in pending if a["run_id"] == ctx.run_id],
        actions=detail.get("actions", []),
    )


def _repair_approval(db, ctx: RunContext, interrupt) -> None:
    """Rebuild a missing approval row from the escalation the gate stashed."""
    tool_use_id = interrupt.id.split(":")[2] if interrupt.id.count(":") >= 2 else ""
    stashed = ctx.escalations.get(tool_use_id)
    if stashed is None:
        logger.warning("interrupt without a stashed escalation id=%s", interrupt.id)
        return
    if interrupt_id_for(stashed.tool_use_id) != interrupt.id:
        logger.warning("interrupt id scheme changed: expected %s", interrupt_id_for(stashed.tool_use_id))
    approval_service.create_approval(
        db,
        business_id=ctx.business_id,
        run_id=ctx.run_id,
        interrupt_id=interrupt.id,
        action_type=stashed.tool_name,
        title=stashed.title,
        reason=stashed.reason,
        recommended_action=stashed.recommended_action,
        payload={"tool": stashed.tool_name, "input": stashed.tool_input},
        evidence=stashed.evidence,
        policy_basis=stashed.policy_basis,
        amount=stashed.amount,
        risk_level=stashed.risk_level,
    )


def _finish(ctx: RunContext, result) -> RunResult:
    """The agent finished. Store its closing summary and token usage."""
    summary = str(result).strip() or None
    usage = getattr(result.metrics, "accumulated_usage", {}) or {}

    with session_scope() as db:
        run_service.complete_run(
            db,
            ctx.run_id,
            summary=summary,
            input_tokens=int(usage.get("inputTokens", 0) or 0),
            output_tokens=int(usage.get("outputTokens", 0) or 0),
        )
        detail = run_service.get_run(db, ctx.business_id, ctx.run_id) or {}

    logger.info(
        "run complete id=%s actions=%d duration=%sms",
        ctx.run_id,
        detail.get("action_count", 0),
        detail.get("duration_ms"),
    )
    return RunResult(
        run_id=ctx.run_id,
        status=RunStatus.COMPLETED,
        summary=summary,
        actions=detail.get("actions", []),
    )
