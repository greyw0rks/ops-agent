"""Conversations and outbound messaging.

`send_message` is the only place an outbound customer message is written. In this
build the channel is simulated — the message is persisted and shown in the
dashboard rather than handed to a mail server — but the boundary is real, so
swapping in SES or a WhatsApp provider is a change in one function.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ConversationStatus, MessageAuthor, MessageDirection
from app.db.models import Conversation, Customer, Message
from app.services.business import get_business
from app.services.common import local_iso

logger = logging.getLogger(__name__)


def get_or_create_conversation(
    db: Session,
    business_id: str,
    customer_id: str | None = None,
    channel: str = "email",
    subject: str | None = None,
) -> Conversation:
    """Reuse the customer's open thread if there is one."""
    if customer_id:
        existing = db.scalars(
            select(Conversation)
            .where(
                Conversation.business_id == business_id,
                Conversation.customer_id == customer_id,
                Conversation.status != ConversationStatus.RESOLVED,
            )
            .order_by(Conversation.last_message_at.desc().nullslast())
        ).first()
        if existing:
            return existing

    conversation = Conversation(
        business_id=business_id, customer_id=customer_id, channel=channel, subject=subject
    )
    db.add(conversation)
    db.flush()
    return conversation


def append_message(
    db: Session,
    conversation: Conversation,
    body: str,
    direction: str = MessageDirection.INBOUND,
    author: str = MessageAuthor.CUSTOMER,
    agent_run_id: str | None = None,
) -> Message:
    now = datetime.now(UTC)
    message = Message(
        conversation_id=conversation.id,
        direction=direction,
        author=author,
        body=body,
        sent_at=now,
        agent_run_id=agent_run_id,
    )
    db.add(message)
    conversation.last_message_at = now
    conversation.status = (
        ConversationStatus.AWAITING_BUSINESS
        if direction == MessageDirection.INBOUND
        else ConversationStatus.AWAITING_CUSTOMER
    )
    db.flush()
    return message


def get_conversation(db: Session, business_id: str, conversation_id: str, limit: int = 30) -> dict:
    """The thread, oldest first, with the customer attached."""
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.business_id != business_id:
        return {"ok": False, "error": f"unknown conversation_id {conversation_id!r}"}

    tz = get_business(db, business_id).timezone
    customer = db.get(Customer, conversation.customer_id) if conversation.customer_id else None
    messages = conversation.messages[-limit:]

    return {
        "ok": True,
        "conversation_id": conversation.id,
        "channel": conversation.channel,
        "subject": conversation.subject,
        "status": conversation.status,
        "customer": (
            {"customer_id": customer.id, "name": customer.name, "email": customer.email}
            if customer
            else None
        ),
        "follow_up_count": conversation.follow_up_count,
        "follow_up_due_at": local_iso(conversation.follow_up_due_at, tz),
        "messages": [
            {
                "message_id": m.id,
                "direction": m.direction,
                "author": m.author,
                "body": m.body,
                "sent_at": local_iso(m.sent_at, tz),
            }
            for m in messages
        ],
    }


DUPLICATE_WINDOW_SECONDS = 300


def _recent_duplicate(db: Session, conversation_id: str, body: str) -> Message | None:
    """The same message, already sent to this thread a moment ago.

    A model that loses track of a completed tool call will happily send the same
    reply twice. The customer should not receive it twice, so identical outbound
    bodies inside a short window are treated as the same message.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=DUPLICATE_WINDOW_SECONDS)
    return db.scalars(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.direction == MessageDirection.OUTBOUND,
            Message.sent_at >= cutoff,
            Message.body == body,
        )
        .order_by(Message.sent_at.desc())
    ).first()


def send_message(
    db: Session,
    business_id: str,
    conversation_id: str,
    body: str,
    agent_run_id: str | None = None,
    follow_up_in_days: int | None = None,
) -> dict:
    """Send an outbound message to the customer and optionally arm a follow-up."""
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.business_id != business_id:
        return {"ok": False, "error": f"unknown conversation_id {conversation_id!r}"}

    tz = get_business(db, business_id).timezone

    duplicate = _recent_duplicate(db, conversation_id, body)
    if duplicate is not None:
        logger.info("suppressed duplicate outbound conversation=%s", conversation.id)
        return {
            "ok": True,
            "sent": False,
            "reason": "duplicate_suppressed",
            "message_id": duplicate.id,
            "conversation_id": conversation.id,
            "sent_at": local_iso(duplicate.sent_at, tz),
            "note": "This exact message was already sent to the customer. Nothing was sent again.",
        }

    message = append_message(
        db,
        conversation,
        body=body,
        direction=MessageDirection.OUTBOUND,
        author=MessageAuthor.AGENT,
        agent_run_id=agent_run_id,
    )

    if follow_up_in_days:
        conversation.follow_up_due_at = datetime.now(UTC) + timedelta(days=follow_up_in_days)
    db.flush()

    logger.info("outbound message conversation=%s chars=%d", conversation.id, len(body))
    return {
        "ok": True,
        "sent": True,
        "message_id": message.id,
        "conversation_id": conversation.id,
        "channel": conversation.channel,
        "sent_at": local_iso(message.sent_at, tz),
        "follow_up_due_at": local_iso(conversation.follow_up_due_at, tz),
        "preview": body[:160],
    }


def set_follow_up(db: Session, conversation_id: str, days: int | None) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        return {"ok": False, "error": "unknown conversation"}
    conversation.follow_up_due_at = (datetime.now(UTC) + timedelta(days=days)) if days else None
    db.flush()
    return {"ok": True, "follow_up_due_at": conversation.follow_up_due_at.isoformat() if days else None}


def resolve_conversation(db: Session, conversation_id: str) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        return {"ok": False, "error": "unknown conversation"}
    conversation.status = ConversationStatus.RESOLVED
    conversation.follow_up_due_at = None
    db.flush()
    return {"ok": True, "conversation_id": conversation.id, "status": conversation.status}


def due_follow_ups(db: Session, business_id: str, now: datetime | None = None) -> list[Conversation]:
    """Conversations the agent promised to chase and has not chased yet."""
    now = now or datetime.now(UTC)
    return list(
        db.scalars(
            select(Conversation).where(
                Conversation.business_id == business_id,
                Conversation.follow_up_due_at.isnot(None),
                Conversation.follow_up_due_at <= now,
                Conversation.status == ConversationStatus.AWAITING_CUSTOMER,
            )
        ).all()
    )
