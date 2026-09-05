"""The policy engine is the security boundary. These tests are the spec for it."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.enums import ApprovalStatus, BookingStatus, PolicyDecision
from app.db.models import Approval, Booking, Business, Customer, Service
from app.policy.engine import evaluate
from app.services import runs as run_service


@pytest.fixture
def completed_booking(db: Session, business: Business, service: Service, customer: Customer) -> Booking:
    """A NGN 15,000 job that finished yesterday — the shape a complaint arrives about."""
    starts = datetime.now(UTC) - timedelta(days=1)
    booking = Booking(
        business_id=business.id,
        customer_id=customer.id,
        service_id=service.id,
        reference="TC-1001",
        starts_at=starts,
        ends_at=starts + timedelta(minutes=service.duration_minutes),
        status=BookingStatus.COMPLETED,
        price=15000,
    )
    db.add(booking)
    db.flush()
    return booking


@pytest.fixture
def run(db: Session, business: Business):
    return run_service.start_run(db, business_id=business.id, trigger="test")


def rule(db, business, run, tool, **args):
    return evaluate(db, business.id, run.id, tool, args)


# --- refunds ---------------------------------------------------------------


def test_small_refund_is_pre_authorised(db, business, run, completed_booking):
    ruling = rule(db, business, run, "issue_refund", booking_id=completed_booking.id, amount=2500)
    assert ruling.decision == PolicyDecision.ALLOW
    assert "5,000" in ruling.reason


def test_mid_band_refund_needs_the_owner(db, business, run, completed_booking):
    ruling = rule(db, business, run, "issue_refund", booking_id=completed_booking.id, amount=7500)
    assert ruling.decision == PolicyDecision.REQUIRE_APPROVAL
    assert ruling.amount == 7500
    assert ruling.title and "TC-1001" in ruling.title
    assert ruling.evidence, "the owner needs records to click through to"


def test_refund_above_the_delegated_ceiling_is_refused(db, business, run, completed_booking):
    completed_booking.price = 200000
    db.flush()
    ruling = rule(db, business, run, "issue_refund", booking_id=completed_booking.id, amount=90000)
    assert ruling.decision == PolicyDecision.DENY
    assert "manual review" in (ruling.policy_basis or "")


def test_refund_cannot_exceed_what_was_paid(db, business, run, completed_booking):
    ruling = rule(db, business, run, "issue_refund", booking_id=completed_booking.id, amount=20000)
    assert ruling.decision == PolicyDecision.DENY
    assert "past the" in ruling.reason


def test_refund_outside_the_claim_window_is_refused(db, business, run, completed_booking):
    completed_booking.ends_at = datetime.now(UTC) - timedelta(days=30)
    db.flush()
    ruling = rule(db, business, run, "issue_refund", booking_id=completed_booking.id, amount=7500)
    assert ruling.decision == PolicyDecision.DENY
    assert "window" in ruling.reason


def test_refund_needs_a_real_booking(db, business, run):
    ruling = rule(db, business, run, "issue_refund", booking_id="book_nope", amount=1000)
    assert ruling.decision == PolicyDecision.DENY


def test_only_one_refund_per_run(db, business, run, completed_booking):
    """A retry loop must not be able to pay a customer twice."""
    run_service.record_action(db, run_id=run.id, tool="issue_refund", output={"ok": True})
    ruling = rule(db, business, run, "issue_refund", booking_id=completed_booking.id, amount=1000)
    assert ruling.decision == PolicyDecision.DENY
    assert "already been issued" in ruling.reason


# --- discounts -------------------------------------------------------------


def test_small_discount_is_pre_authorised(db, business, run, completed_booking):
    ruling = rule(db, business, run, "apply_discount", booking_id=completed_booking.id, percent=10)
    assert ruling.decision == PolicyDecision.ALLOW


def test_mid_band_discount_needs_the_owner(db, business, run, completed_booking):
    ruling = rule(db, business, run, "apply_discount", booking_id=completed_booking.id, percent=20)
    assert ruling.decision == PolicyDecision.REQUIRE_APPROVAL
    assert ruling.amount == 3000  # 20% of 15,000


def test_large_discount_is_refused(db, business, run, completed_booking):
    ruling = rule(db, business, run, "apply_discount", booking_id=completed_booking.id, percent=40)
    assert ruling.decision == PolicyDecision.DENY


# --- cancellations ---------------------------------------------------------


def test_cancellation_with_notice_is_free_and_delegated(db, business, run, completed_booking):
    completed_booking.starts_at = datetime.now(UTC) + timedelta(days=3)
    completed_booking.status = BookingStatus.CONFIRMED
    db.flush()
    ruling = rule(db, business, run, "cancel_booking", booking_id=completed_booking.id)
    assert ruling.decision == PolicyDecision.ALLOW


def test_late_cancellation_asks_about_the_fee(db, business, run, completed_booking):
    completed_booking.starts_at = datetime.now(UTC) + timedelta(hours=3)
    completed_booking.status = BookingStatus.CONFIRMED
    db.flush()
    ruling = rule(db, business, run, "cancel_booking", booking_id=completed_booking.id)
    assert ruling.decision == PolicyDecision.REQUIRE_APPROVAL
    assert ruling.amount == 4500  # 30% of 15,000


# --- messaging while a decision is open ------------------------------------


def test_no_outbound_message_while_a_decision_is_pending(db, business, run):
    """The agent must not tell a customer something the owner has not agreed to."""
    db.add(
        Approval(
            business_id=business.id,
            run_id=run.id,
            interrupt_id="v1:before_tool_call:x:y",
            action_type="issue_refund",
            title="Refund",
            reason="over the limit",
            recommended_action="refund",
            status=ApprovalStatus.PENDING,
        )
    )
    db.flush()
    ruling = rule(db, business, run, "send_message", body="Your refund is on its way!")
    assert ruling.decision == PolicyDecision.DENY
    assert "still open" in ruling.reason


def test_messaging_is_allowed_once_the_decision_is_made(db, business, run):
    db.add(
        Approval(
            business_id=business.id,
            run_id=run.id,
            interrupt_id="v1:before_tool_call:x:y",
            action_type="issue_refund",
            title="Refund",
            reason="over the limit",
            recommended_action="refund",
            status=ApprovalStatus.APPROVED,
        )
    )
    db.flush()
    ruling = rule(db, business, run, "send_message", body="Your refund has been processed.")
    assert ruling.decision == PolicyDecision.ALLOW


# --- rescheduling ----------------------------------------------------------


def test_reschedule_within_the_allowance_is_delegated(db, business, run, completed_booking):
    completed_booking.starts_at = datetime.now(UTC) + timedelta(days=2)
    db.flush()
    ruling = rule(db, business, run, "reschedule_booking", booking_id=completed_booking.id)
    assert ruling.decision == PolicyDecision.ALLOW


def test_third_reschedule_needs_the_owner(db, business, run, completed_booking):
    completed_booking.notes = "Rescheduled: customer away\nRescheduled: rain"
    db.flush()
    ruling = rule(db, business, run, "reschedule_booking", booking_id=completed_booking.id)
    assert ruling.decision == PolicyDecision.REQUIRE_APPROVAL


# --- the escape hatch ------------------------------------------------------


def test_agent_can_always_ask_for_a_human(db, business, run):
    ruling = rule(
        db,
        business,
        run,
        "request_approval",
        action_type="goodwill_credit",
        title="Goodwill credit for Ada",
        reason="Third complaint this quarter.",
        recommended_action="Credit her next clean.",
    )
    assert ruling.decision == PolicyDecision.REQUIRE_APPROVAL
    assert ruling.action_type == "goodwill_credit"


def test_read_only_tools_are_never_gated(db, business, run):
    for tool in ("find_customer", "get_customer_history", "check_availability", "calculate_price"):
        assert evaluate(db, business.id, run.id, tool, {}).decision == PolicyDecision.ALLOW


def test_unknown_tool_is_denied(db, business, run):
    ruling = evaluate(db, business.id, run.id, "wire_transfer", {"amount": 999999})
    assert ruling.decision == PolicyDecision.DENY
