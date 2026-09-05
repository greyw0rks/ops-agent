"""The gate's contract with Strands, and the defences behind it.

The interrupt-id test matters more than it looks: the gate writes an approval row
keyed to an id it predicts, so that the owner's queue is populated before the run
pauses. If a future SDK release changes how that id is built, this test fails
rather than the approvals silently detaching from their runs.
"""

import pytest
from strands.hooks.events import BeforeToolCallEvent

from app.policy.gate import GATE_NAME, interrupt_id_for
from app.services.billing import PolicyViolation, apply_discount, issue_refund


def test_predicted_interrupt_id_matches_the_sdk():
    tool_use = {"name": "issue_refund", "toolUseId": "toolu_abc123", "input": {}}
    event = BeforeToolCallEvent(selected_tool=None, tool_use=tool_use, invocation_state={}, agent=None)
    assert event._interrupt_id(GATE_NAME) == interrupt_id_for("toolu_abc123")


def test_predicted_id_is_stable_across_calls():
    assert interrupt_id_for("toolu_x") == interrupt_id_for("toolu_x")
    assert interrupt_id_for("toolu_x") != interrupt_id_for("toolu_y")


# --- the service layer refuses out-of-bounds writes even if the gate is bypassed ---


@pytest.fixture
def paid_booking(db, business, service, customer):
    from datetime import UTC, datetime, timedelta

    from app.db.models import Booking

    starts = datetime.now(UTC) - timedelta(days=1)
    booking = Booking(
        business_id=business.id,
        customer_id=customer.id,
        service_id=service.id,
        reference="TC-3001",
        starts_at=starts,
        ends_at=starts + timedelta(hours=2),
        status="completed",
        price=15000,
    )
    db.add(booking)
    db.flush()
    return booking


def test_refund_service_refuses_above_the_ceiling_without_an_approval(db, business, paid_booking):
    paid_booking.price = 200000
    db.flush()
    with pytest.raises(PolicyViolation):
        issue_refund(db, business.id, paid_booking.id, amount=90000, reason="test")


def test_refund_service_allows_above_the_ceiling_with_an_approval(db, business, paid_booking):
    paid_booking.price = 200000
    db.flush()
    result = issue_refund(
        db, business.id, paid_booking.id, amount=90000, reason="test", approval_id="apr_x"
    )
    assert result["ok"]
    assert result["authorised_by_approval"] == "apr_x"


def test_refund_service_refuses_more_than_was_paid(db, business, paid_booking):
    result = issue_refund(db, business.id, paid_booking.id, amount=20000, reason="test")
    assert not result["ok"]
    assert result["already_refunded"] == 0


def test_partial_refunds_accumulate(db, business, paid_booking):
    issue_refund(db, business.id, paid_booking.id, amount=4000, reason="first")
    second = issue_refund(db, business.id, paid_booking.id, amount=4000, reason="second")
    assert second["total_refunded_on_booking"] == 8000


def test_full_refund_cancels_the_booking(db, business, paid_booking):
    issue_refund(db, business.id, paid_booking.id, amount=15000, reason="full")
    assert paid_booking.status == "cancelled"


def test_discount_service_refuses_above_the_ceiling_without_an_approval(db, business, paid_booking):
    with pytest.raises(PolicyViolation):
        apply_discount(db, business.id, paid_booking.id, percent=40, reason="test")


def test_discount_reduces_the_price_and_records_why(db, business, paid_booking):
    result = apply_discount(db, business.id, paid_booking.id, percent=10, reason="goodwill")
    assert result["new_price"] == 13500
    assert paid_booking.price_breakdown["adjustments"][0]["percent"] == 10
