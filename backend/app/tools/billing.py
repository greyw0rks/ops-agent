"""Money tools: refunds, discounts, supplier invoices.

The docstrings tell the model what these are for. What it is allowed to do with
them is decided by `app.policy` before the function is ever entered — a refund
above the owner's limit pauses the run rather than executing.
"""

from datetime import UTC, datetime

from strands import tool

from app.db.session import session_scope
from app.services import billing as service
from app.tools._context import approval_for, current


@tool
def issue_refund(booking_id: str, amount: float, reason: str) -> dict:
    """Refund money against a booking.

    Read the refund policy and the customer's history before proposing an amount.
    Small refunds inside the owner's pre-authorised limit go straight through;
    larger ones pause for the owner's decision and you will be resumed once they
    have chosen. Amounts above the owner's ceiling are refused outright — open a
    task instead.

    Args:
        booking_id: The booking being refunded, by id or reference.
        amount: How much to refund, in the business's currency.
        reason: Why — this is what the owner reads when deciding.

    Returns:
        The refund record, including which approval authorised it.
    """
    ctx = current()
    with session_scope() as db:
        approval = approval_for(db, ctx.run_id, "issue_refund")
        try:
            result = service.issue_refund(
                db,
                ctx.business_id,
                booking_id=booking_id,
                amount=amount,
                reason=reason,
                approval_id=approval.id if approval else None,
                agent_run_id=ctx.run_id,
            )
        except service.PolicyViolation as exc:
            return {"ok": False, "error": "policy_violation", "detail": str(exc)}
        return _with_approval(result, approval)


@tool
def apply_discount(booking_id: str, percent: float, reason: str) -> dict:
    """Reduce a booking's price by a percentage.

    Use this for goodwill on a future or upcoming job, where a refund is not the
    right instrument. Small discounts are pre-authorised; larger ones need the
    owner.

    Args:
        booking_id: The booking to discount, by id or reference.
        percent: The percentage to take off, e.g. `10`.
        reason: Why the discount is warranted.

    Returns:
        The old and new price, and which approval authorised it.
    """
    ctx = current()
    with session_scope() as db:
        approval = approval_for(db, ctx.run_id, "apply_discount")
        try:
            result = service.apply_discount(
                db,
                ctx.business_id,
                booking_id=booking_id,
                percent=percent,
                reason=reason,
                approval_id=approval.id if approval else None,
            )
        except service.PolicyViolation as exc:
            return {"ok": False, "error": "policy_violation", "detail": str(exc)}
        return _with_approval(result, approval)


def _with_approval(result: dict, approval) -> dict:
    """Surface who authorised the action, and anything they said about it."""
    if approval is None or not result.get("ok"):
        return result
    result["approved_by"] = approval.decided_by
    if approval.decision_note:
        result["owner_note"] = approval.decision_note
    return result


@tool
def record_supplier_invoice(
    supplier_name: str,
    amount: float,
    reference: str | None = None,
    issued_date: str | None = None,
    due_date: str | None = None,
    document_key: str | None = None,
    extracted: dict | None = None,
) -> dict:
    """File a supplier invoice against the business's records.

    Call this after reading an incoming invoice document. An identical
    supplier-and-reference pair is refused as a duplicate, which is the common
    failure mode when the same invoice is emailed twice.

    Args:
        supplier_name: Who issued it.
        amount: The total due.
        reference: The supplier's invoice number.
        issued_date: Invoice date as `YYYY-MM-DD`.
        due_date: Payment due date as `YYYY-MM-DD`.
        document_key: Where the source document is stored.
        extracted: The raw fields you read off the document, kept for audit.

    Returns:
        The filed invoice, or `duplicate_invoice` with the existing record.
    """
    ctx = current()
    with session_scope() as db:
        return service.record_supplier_invoice(
            db,
            ctx.business_id,
            supplier_name=supplier_name,
            amount=amount,
            reference=reference,
            issued_at=_parse_date(issued_date),
            due_at=_parse_date(due_date),
            document_key=document_key,
            extracted=extracted,
            agent_run_id=ctx.run_id,
        )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None
