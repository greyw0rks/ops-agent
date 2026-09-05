"""Communication tools."""

from strands import tool

from app.db.session import session_scope
from app.services import conversations as service
from app.tools._context import current


@tool
def get_conversation(conversation_id: str | None = None) -> dict:
    """Read the message thread you are working in.

    Call this first on any customer-message event: it is where the actual request
    is. With no argument it returns the thread that triggered this run.

    Args:
        conversation_id: Optional. Defaults to the conversation for this event.

    Returns:
        The thread oldest-first, with the customer attached and follow-up state.
    """
    ctx = current()
    target = conversation_id or ctx.conversation_id
    if not target:
        return {"ok": False, "error": "no conversation is associated with this event"}
    with session_scope() as db:
        return service.get_conversation(db, ctx.business_id, target)


@tool
def send_message(
    body: str,
    conversation_id: str | None = None,
    follow_up_in_days: int | None = None,
) -> dict:
    """Send a reply to the customer.

    Write it as the business would: address them by name, confirm the specifics you
    have actually recorded (date, time, price, reference), and keep it short. Never
    promise something you have not already done — if a refund is waiting on the
    owner, do not mention it as though it is settled.

    Set `follow_up_in_days` when you are waiting on the customer for something, such
    as accepting a quote. You will be woken up to chase it if they go quiet.

    Args:
        body: The message to send.
        conversation_id: Optional. Defaults to this event's conversation.
        follow_up_in_days: Chase this thread after N days of silence.

    Returns:
        Confirmation with the message id and when any follow-up is due.
    """
    ctx = current()
    target = conversation_id or ctx.conversation_id
    if not target:
        return {"ok": False, "error": "no conversation to reply to"}
    with session_scope() as db:
        return service.send_message(
            db,
            ctx.business_id,
            target,
            body=body,
            agent_run_id=ctx.run_id,
            follow_up_in_days=follow_up_in_days,
        )


@tool
def resolve_conversation(conversation_id: str | None = None) -> dict:
    """Close a thread once nothing further is owed on either side.

    Use this after a booking is confirmed or a complaint is settled, so the
    follow-up sweep stops looking at it.

    Args:
        conversation_id: Optional. Defaults to this event's conversation.

    Returns:
        The conversation's new status.
    """
    ctx = current()
    target = conversation_id or ctx.conversation_id
    if not target:
        return {"ok": False, "error": "no conversation to resolve"}
    with session_scope() as db:
        return service.resolve_conversation(db, target)
