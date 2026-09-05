"""Availability, booking writes, and pricing.

These are the calculations the agent is not allowed to do in its head.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.enums import BookingStatus
from app.db.models import Booking, Business, Customer, Service
from app.services.bookings import (
    cancel_booking,
    check_availability,
    create_booking,
    reschedule_booking,
)
from app.services.business import calculate_price


def next_weekday(days_ahead: int = 1) -> datetime:
    """The next Monday-to-Friday day at least `days_ahead` out, in UTC."""
    day = datetime.now(UTC) + timedelta(days=days_ahead)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day


@pytest.fixture
def open_day() -> str:
    return next_weekday(2).date().isoformat()


# --- availability ----------------------------------------------------------


def test_availability_lists_slots_within_opening_hours(db, business, service, open_day):
    result = check_availability(db, business.id, service.id, open_day)
    assert result["available"]
    starts = [s["start"] for s in result["slots"]]
    # 09:00-17:00 with a 120-minute job means the last start is 15:00.
    assert starts[0] == "09:00"
    assert starts[-1] == "15:00"


def test_availability_respects_a_closed_day(db, business, service):
    saturday = datetime.now(UTC)
    while saturday.weekday() != 5:
        saturday += timedelta(days=1)
    result = check_availability(db, business.id, service.id, saturday.date().isoformat())
    assert not result["available"]
    assert result["reason"] == "closed"


def test_availability_filters_by_period(db, business, service, open_day):
    result = check_availability(db, business.id, service.id, open_day, preferred_period="afternoon")
    assert all(int(s["start"][:2]) >= 12 for s in result["slots"])


def test_availability_drops_a_slot_once_capacity_is_gone(
    db, business: Business, service: Service, customer: Customer, open_day
):
    start = datetime.fromisoformat(f"{open_day}T09:00:00+00:00")
    for i in range(business.concurrent_capacity):
        db.add(
            Booking(
                business_id=business.id,
                customer_id=customer.id,
                service_id=service.id,
                reference=f"TC-200{i}",
                starts_at=start,
                ends_at=start + timedelta(minutes=service.duration_minutes),
                status=BookingStatus.CONFIRMED,
                price=7500,
            )
        )
    db.flush()

    result = check_availability(db, business.id, service.id, open_day)
    assert "09:00" not in [s["start"] for s in result["slots"]]


def test_availability_never_offers_a_past_slot(db, business, service):
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    result = check_availability(db, business.id, service.id, yesterday)
    assert result["slots"] == []


def test_availability_rejects_a_malformed_date(db, business, service):
    result = check_availability(db, business.id, service.id, "next Saturday")
    assert not result["available"]
    assert "YYYY-MM-DD" in result["error"]


# --- creating --------------------------------------------------------------


def test_create_booking_writes_a_reference_and_price(db, business, service, customer, open_day):
    result = create_booking(
        db, business.id, customer.id, service.id, open_day, "10:00", price=10500
    )
    assert result["ok"]
    assert result["reference"].startswith("TC-")
    assert result["price"] == 10500
    assert result["created_by"] == "agent"


def test_create_booking_refuses_a_time_outside_opening_hours(
    db, business, service, customer, open_day
):
    result = create_booking(db, business.id, customer.id, service.id, open_day, "22:00")
    assert not result["ok"]
    assert result["error"] == "outside opening hours"


def test_create_booking_refuses_the_past(db, business, service, customer):
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    result = create_booking(db, business.id, customer.id, service.id, yesterday, "10:00")
    assert not result["ok"]


def test_create_booking_rechecks_capacity_at_write_time(
    db, business, service, customer, open_day
):
    """Availability can go stale between the check and the write."""
    for _ in range(business.concurrent_capacity):
        assert create_booking(db, business.id, customer.id, service.id, open_day, "11:00")["ok"]
    result = create_booking(db, business.id, customer.id, service.id, open_day, "11:00")
    assert not result["ok"]
    assert result["error"] == "slot is full"


# --- moving and cancelling -------------------------------------------------


def test_reschedule_moves_the_booking(db, business, service, customer, open_day):
    created = create_booking(db, business.id, customer.id, service.id, open_day, "10:00")
    later = next_weekday(5).date().isoformat()
    result = reschedule_booking(db, business.id, created["booking_id"], later, "13:00")
    assert result["ok"]
    assert result["previous_starts_at"] != result["starts_at"]


def test_reschedule_refuses_inside_the_notice_window(
    db, business, service, customer, open_day
):
    created = create_booking(db, business.id, customer.id, service.id, open_day, "10:00")
    booking = db.get(Booking, created["booking_id"])
    booking.starts_at = datetime.now(UTC) + timedelta(hours=1)
    db.flush()

    later = next_weekday(5).date().isoformat()
    result = reschedule_booking(db, business.id, booking.id, later, "13:00")
    assert not result["ok"]
    assert result["min_notice_hours"] == 4


def test_cancellation_reports_the_fee_the_policy_implies(
    db, business, service, customer, open_day
):
    created = create_booking(db, business.id, customer.id, service.id, open_day, "10:00", price=10000)
    booking = db.get(Booking, created["booking_id"])
    booking.starts_at = datetime.now(UTC) + timedelta(hours=2)
    db.flush()

    result = cancel_booking(db, business.id, booking.id, reason="customer travelling")
    assert result["ok"]
    assert result["late_cancellation"]
    assert result["cancellation_fee"] == 3000


def test_lookup_by_customer_facing_reference(db, business, service, customer, open_day):
    created = create_booking(db, business.id, customer.id, service.id, open_day, "10:00")
    result = cancel_booking(db, business.id, created["reference"], reason="test")
    assert result["ok"]


# --- pricing ---------------------------------------------------------------


def test_price_includes_one_of_each_modifier_in_the_base(db, business, service):
    result = calculate_price(db, business.id, service.id, quantities={"bedrooms": 1})
    assert result["price"] == 7500


def test_extra_bedrooms_are_charged(db, business, service):
    result = calculate_price(db, business.id, service.id, quantities={"bedrooms": 3})
    assert result["price"] == 10500
    assert len(result["breakdown"]) == 2


def test_undeclared_extras_cannot_be_invented(db, business, service):
    """The model cannot add a line item the service does not charge for."""
    result = calculate_price(db, business.id, service.id, quantities={"chandeliers": 9})
    assert result["price"] == 7500
