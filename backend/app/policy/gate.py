"""The enforcement point.

`PolicyGate` is a Strands `InterventionHandler`. Every tool call the model makes
passes through `before_tool_call` before the tool function is entered, so this is
the one place where "the agent wants to do X" becomes "the agent is allowed to do
X". Three outcomes:

* `Proceed`  — the owner delegated this; run it and log it.
* `Deny`     — out of bounds. The model is told why and continues without it.
* `Confirm`  — needs a human. Strands pauses the run; the approval row we write
               here is what the owner sees, and resolving it resumes this exact
               tool call.
"""

import logging
import uuid

from strands.interventions import Confirm, Deny, InterventionHandler, Proceed, Transform

from app.db.enums import ActionStatus, ApprovalStatus, PolicyDecision
from app.db.session import session_scope
from app.policy.engine import Ruling, evaluate
from app.services import approvals as approval_service
from app.services import runs as run_service
from app.tools import _context as run_context
from app.tools._context import PendingEscalation

logger = logging.getLogger(__name__)

GATE_NAME = "policy-gate"


def interrupt_id_for(tool_use_id: str, handler_name: str = GATE_NAME) -> str:
    """Reproduce the interrupt id Strands will generate for this confirmation.

    Mirrors `BeforeToolCallEvent._interrupt_id`. Knowing it up front lets us write
    the approval row before the run pauses, so the owner's queue is never behind
    the agent's state.
    """
    return f"v1:before_tool_call:{tool_use_id}:{uuid.uuid5(uuid.NAMESPACE_OID, handler_name)}"


def _append_result_text(event, text: str) -> None:
    """Add a text block to a tool result the agent is about to read."""
    result = getattr(event, "result", None)
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        result["content"].append({"text": text})


class PolicyGate(InterventionHandler):
    """Enforces the business's operating rules on every tool call."""

    name = GATE_NAME

    def before_tool_call(self, event, **kwargs):
        tool_use = event.tool_use
        tool_name = tool_use.get("name", "")
        tool_input = tool_use.get("input") or {}
        tool_use_id = tool_use.get("toolUseId", "")

        ctx = run_context.current_or_none()
        if ctx is None:
            # No run bound (direct tool invocation in a test); nothing to enforce against.
            return Proceed()

        with session_scope() as db:
            ruling = evaluate(db, ctx.business_id, ctx.run_id, tool_name, tool_input)

            if ruling.decision == PolicyDecision.ALLOW:
                logger.debug("gate allow tool=%s run=%s", tool_name, ctx.run_id)
                return Proceed(reason=ruling.reason)

            if ruling.decision == PolicyDecision.DENY:
                run_service.record_action(
                    db,
                    run_id=ctx.run_id,
                    tool=tool_name,
                    tool_input=tool_input,
                    output={"blocked": True, "reason": ruling.reason},
                    status=ActionStatus.BLOCKED,
                    risk_level=ruling.risk_level,
                    policy_decision=ruling.decision,
                    policy_reason=ruling.reason,
                    tool_use_id=tool_use_id,
                )
                logger.info("gate deny tool=%s run=%s reason=%s", tool_name, ctx.run_id, ruling.reason)
                return Deny(reason=f"{ruling.reason} (policy: {ruling.policy_basis})")

            approval = self._open_approval(db, ctx, tool_name, tool_use_id, tool_input, ruling)

        logger.info("gate escalate tool=%s run=%s approval=%s", tool_name, ctx.run_id, approval)
        return Confirm(
            prompt=ruling.recommended_action or f"Approve {tool_name}?",
            reason=ruling.reason,
        )

    def after_tool_call(self, event, **kwargs):
        """Pass the owner's reasoning back to the agent, not just their verdict.

        When a confirmation is refused, Strands cancels the tool with a terse
        message. If the owner left a note explaining why, the agent should see it —
        that is the difference between "no" and "no, offer her a free re-clean
        instead".
        """
        cancel_message = getattr(event, "cancel_message", None)
        if not cancel_message or not str(cancel_message).startswith("CONFIRMATION_FAILED"):
            return Proceed()

        ctx = run_context.current_or_none()
        if ctx is None:
            return Proceed()

        tool_use_id = event.tool_use.get("toolUseId", "")
        with session_scope() as db:
            approval = approval_service.find_by_interrupt(db, ctx.run_id, interrupt_id_for(tool_use_id))
            if approval is None or approval.status != ApprovalStatus.REJECTED:
                return Proceed()
            note = approval.decision_note
            decided_by = approval.decided_by or "the owner"

        explanation = (
            f"The {decided_by} rejected this. "
            + (f'Their reason: "{note}". ' if note else "")
            + "Do not carry it out. Handle the situation another way and only tell the "
            "customer what is actually true."
        )
        return Transform(apply=lambda e: _append_result_text(e, explanation))

    # -- internals ---------------------------------------------------------

    def _open_approval(self, db, ctx, tool_name, tool_use_id, tool_input, ruling: Ruling) -> str:
        """Create (or reuse) the pending decision for this tool call.

        The early return is not an optimisation. An interrupt is re-execution, not
        continuation: on resume the framework runs this handler again from the top and
        only `interrupt()` returns early with the stored answer, so everything above the
        `Confirm` happens twice. Keying on the interrupt id makes the second pass a
        no-op — otherwise one escalation would ask the owner twice and count itself
        twice in the audit trail. `tests/test_gate_resume.py` drives both passes.
        """
        interrupt_id = interrupt_id_for(tool_use_id)
        existing = approval_service.find_by_interrupt(db, ctx.run_id, interrupt_id)
        if existing is not None:
            return existing.id

        approval = approval_service.create_approval(
            db,
            business_id=ctx.business_id,
            run_id=ctx.run_id,
            interrupt_id=interrupt_id,
            action_type=ruling.action_type or tool_name,
            title=ruling.title or f"Approve {tool_name}",
            reason=ruling.reason,
            recommended_action=ruling.recommended_action or f"Run {tool_name}",
            payload={"tool": tool_name, "input": tool_input},
            evidence=ruling.evidence,
            policy_basis=ruling.policy_basis,
            amount=ruling.amount,
            risk_level=ruling.risk_level,
        )
        run_service.record_action(
            db,
            run_id=ctx.run_id,
            tool=tool_name,
            tool_input=tool_input,
            output={"escalated": True, "approval_id": approval.id},
            status=ActionStatus.AWAITING_APPROVAL,
            risk_level=ruling.risk_level,
            policy_decision=PolicyDecision.REQUIRE_APPROVAL,
            policy_reason=ruling.reason,
            approval_id=approval.id,
            tool_use_id=tool_use_id,
        )
        run_service.mark_awaiting_approval(db, ctx.run_id)

        ctx.escalations[tool_use_id] = PendingEscalation(
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            tool_input=tool_input,
            title=approval.title,
            reason=approval.reason,
            recommended_action=approval.recommended_action,
            policy_basis=approval.policy_basis,
            risk_level=approval.risk_level,
            amount=ruling.amount,
            evidence=ruling.evidence,
        )
        return approval.id
