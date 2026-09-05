"""Conversation handling, including the duplicate-reply guard."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.enums import ConversationStatus, MessageDirection
from app.db.models import Conversation, Message
from app.services.conversations import (
    append_message,
    due_follow_ups,
    get_conversation,
    resolve_conversation,
    send_message,
)


@pytest.fixture
def thread(db: Session, business, customer) -> Conversation:
    conversation = Conversation(
        business_id=business.id,
        customer_id=customer.id,
        channel="email",
        subject="Cleaning next week",
        status=ConversationStatus.AWAITING_BUSINESS,
    )
    db.add(conversation)
    db.flush()
    append_message(db, conversation, "Can I book a clean for Thursday?")
    return conversation


def test_thread_reads_oldest_first_with_the_customer_attached(db, business, thread, customer):
    result = get_conversation(db, business.id, thread.id)
    assert result["ok"]
    assert result["customer"]["name"] == customer.name
    assert result["messages"][0]["direction"] == MessageDirection.INBOUND


def test_sending_a_reply_flips_the_thread_to_awaiting_customer(db, business, thread):
    result = send_message(db, business.id, thread.id, "Thursday at 10:00 works — booked.")
    assert result["sent"]
    assert thread.status == ConversationStatus.AWAITING_CUSTOMER


def test_identical_reply_is_not_sent_twice(db, business, thread):
    """A model that loses track of a completed call must not double-message a customer."""
    body = "Thursday at 10:00 works — booked. Your reference is TC-1042."
    first = send_message(db, business.id, thread.id, body)
    second = send_message(db, business.id, thread.id, body)

    assert first["sent"] is True
    assert second["sent"] is False
    assert second["reason"] == "duplicate_suppressed"
    assert second["message_id"] == first["message_id"]

    outbound = db.query(Message).filter(
        Message.conversation_id == thread.id, Message.direction == MessageDirection.OUTBOUND
    )
    assert outbound.count() == 1


def test_a_different_reply_still_goes_out(db, business, thread):
    send_message(db, business.id, thread.id, "Booked for Thursday.")
    second = send_message(db, business.id, thread.id, "One more thing — please leave the gate key out.")
    assert second["sent"] is True


def test_follow_up_is_armed_when_waiting_on_the_customer(db, business, thread):
    result = send_message(db, business.id, thread.id, "Here is your quote.", follow_up_in_days=3)
    assert result["follow_up_due_at"] is not None


def test_follow_up_sweep_finds_only_overdue_threads_awaiting_the_customer(db, business, thread):
    send_message(db, business.id, thread.id, "Here is your quote.", follow_up_in_days=3)
    assert due_follow_ups(db, business.id) == []

    thread.follow_up_due_at = datetime.now(UTC) - timedelta(hours=1)
    db.flush()
    assert [c.id for c in due_follow_ups(db, business.id)] == [thread.id]


def test_resolving_a_thread_clears_its_follow_up(db, business, thread):
    send_message(db, business.id, thread.id, "Here is your quote.", follow_up_in_days=3)
    resolve_conversation(db, thread.id)
    assert thread.status == ConversationStatus.RESOLVED
    assert thread.follow_up_due_at is None
    assert due_follow_ups(db, business.id) == []


def test_unknown_conversation_is_reported_not_raised(db, business):
    assert get_conversation(db, business.id, "conv_nope")["ok"] is False
    assert send_message(db, business.id, "conv_nope", "hello")["ok"] is False
