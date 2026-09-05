"""Approval tools.

`request_approval` is the escape hatch for judgement the agent should not exercise
on its own even when no policy rule forbids it. Calling it pauses the run: the
policy gate turns the call into a pending decision, and the tool body only runs
once a human has chosen — at which point it reports what they decided.
"""

from strands import tool

from app.db.enums import ApprovalStatus
from app.db.session import session_scope
from app.services import approvals as service
from app.tools._context import current


@tool
def request_approval(
    action_type: str,
    title: str,
    reason: str,
    recommended_action: str,
    amount: float | None = None,
) -> dict:
    """Ask the owner to decide something before you act on it.

    Use this when the right move is clear to you but is not yours to make: a
    goodwill gesture outside the usual policy, an exception for a long-standing
    customer, anything where being wrong would cost the business money or trust.

    Do not use it as a substitute for work you can do yourself, and do not use it
    for refunds or discounts — those are gated automatically, so just call the tool
    and you will be paused if the owner is needed.

    Calling this stops your run. You will be resumed with the decision.

    Args:
        action_type: A short label for what you are asking about, e.g. `goodwill_credit`.
        title: One line the owner will see in their queue.
        reason: The situation and why you think this is right.
        recommended_action: Exactly what you would do if they say yes.
        amount: The money involved, if any.

    Returns:
        `approved` true or false, plus any note the owner left.
    """
    ctx = current()
    with session_scope() as db:
        approval = service.find_latest_by_action(db, ctx.run_id, action_type)
        if approval is None:
            return {"ok": False, "error": "no decision was recorded for this request"}
        return {
            "ok": True,
            "approval_id": approval.id,
            "approved": approval.status == ApprovalStatus.APPROVED,
            "status": approval.status,
            "decided_by": approval.decided_by,
            "note": approval.decision_note,
        }


@tool
def get_approval_status(approval_id: str) -> dict:
    """Check where a decision you raised has got to.

    Args:
        approval_id: The approval to check.

    Returns:
        Its current status and, if decided, who decided it and any note.
    """
    ctx = current()
    with session_scope() as db:
        approval = service.get_approval(db, ctx.business_id, approval_id)
        if approval is None:
            return {"ok": False, "error": f"unknown approval_id {approval_id!r}"}
        return {
            "ok": True,
            "approval_id": approval.id,
            "status": approval.status,
            "approved": approval.status == ApprovalStatus.APPROVED,
            "decided_by": approval.decided_by,
            "note": approval.decision_note,
        }
