"""Booking lifecycle: availability, creation, rescheduling, cancellation.

Availability is computed from the business's opening hours, its concurrent
capacity, and the bookings already on the calendar. The agent asks this service
what is possible; it does not get to decide for itself.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import BookingStatus
from app.db.models import Booking, Business, Service, parse_hhmm
from app.services.business import get_business, get_service
from app.services.common import (
    local_iso,
    money,
    overlaps,
    period_window,
    to_local,
    to_utc,
)

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

ACTIVE_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED)


def _reference_prefix(business: Business) -> str:
    """Two-letter prefix for booking references: "BrightHome Services" -> BH."""
    capitals = [ch for ch in business.name if ch.isupper()]
    if len(capitals) >= 2:
        return "".join(capitals[:2])
    initials = "".join(word[0] for word in business.name.split()[:2] if word)
    return (initials or "OP").upper()


def next_reference(db: Session, business: Business) -> str:
    """Sequential, human-quotable booking reference such as `BH-1042`."""
    total = db.scalar(
        select(func.count()).select_from(Booking).where(Booking.business_id == business.id)
    )
    return f"{_reference_prefix(business)}-{1041 + (total or 0)}"


def _day_window(business: Business, day: date) -> tuple[datetime, datetime] | None:
    """Opening and closing time for a given calendar day, in UTC."""
    hours = business.opening_hours or {}
    spec = hours.get(WEEKDAY_KEYS[day.weekday()])
    if not spec:
        return None
    opens, closes = parse_hhmm(spec[0]), parse_hhmm(spec[1])
    return (
        to_utc(datetime.combine(day, opens), business.timezone),
        to_utc(datetime.combine(day, closes), business.timezone),
    )


def _bookings_on(db: Session, business_id: str, start: datetime, end: datetime) -> list[Booking]:
    return list(
        db.scalars(
            select(Booking).where(
                Booking.business_id == business_id,
                Booking.status.in_(ACTIVE_STATUSES),
                Booking.starts_at < end,
                Booking.ends_at > start,
            )
        ).all()
    )


def check_availability(
    db: Session,
    business_id: str,
    service_id: str,
    day: str,
    preferred_period: str | None = None,
    exclude_booking_id: str | None = None,
) -> dict:
    """List the slots a service can actually be delivered in on a given day."""
    business = get_business(db, business_id)
    service = get_service(db, business_id, service_id)
    if service is None:
        return {"available": False, "error": f"unknown service_id {service_id!r}", "slots": []}

    try:
        target = date.fromisoformat(day)
    except ValueError:
        return {"available": False, "error": f"date must be YYYY-MM-DD, got {day!r}", "slots": []}

    window = _day_window(business, target)
    if window is None:
        return {
            "available": False,
            "reason": "closed",
            "message": f"{business.name} is closed on {target.strftime('%A')}s.",
            "date": day,
            "slots": [],
        }

    opens_at, closes_at = window
    duration = timedelta(minutes=service.duration_minutes)
    interval = timedelta(minutes=business.slot_interval_minutes)
    period_start_hour, period_end_hour = period_window(preferred_period)

    existing = [
        b for b in _bookings_on(db, business_id, opens_at, closes_at) if b.id != exclude_booking_id
    ]
    now = datetime.now(UTC)

    slots: list[dict] = []
    cursor = opens_at
    while cursor + duration <= closes_at:
        local_start = to_local(cursor, business.timezone)
        in_period = period_start_hour <= local_start.hour < period_end_hour
        if in_period and cursor > now:
            concurrent = sum(
                1 for b in existing if overlaps(cursor, cursor + duration, b.starts_at, b.ends_at)
            )
            if concurrent < business.concurrent_capacity:
                slots.append(
                    {
                        "start": local_start.strftime("%H:%M"),
                        "starts_at": local_start.isoformat(),
                        "ends_at": to_local(cursor + duration, business.timezone).isoformat(),
                        "remaining_capacity": business.concurrent_capacity - concurrent,
                    }
                )
        cursor += interval

    return {
        "available": bool(slots),
        "date": day,
        "service_id": service.id,
        "service_name": service.name,
        "duration_minutes": service.duration_minutes,
        "preferred_period": preferred_period or "any",
        "timezone": business.timezone,
        "slots": slots,
        "message": None
        if slots
        else f"No {preferred_period or 'open'} slots left on {target.isoformat()}.",
    }


def booking_dict(db: Session, booking: Booking, tz: str | None = None) -> dict:
    """Serialise a booking for a tool result."""
    if tz is None:
        tz = get_business(db, booking.business_id).timezone
    service = db.get(Service, booking.service_id)
    return {
        "booking_id": booking.id,
        "reference": booking.reference,
        "customer_id": booking.customer_id,
        "service_id": booking.service_id,
        "service_name": service.name if service else None,
        "starts_at": local_iso(booking.starts_at, tz),
        "ends_at": local_iso(booking.ends_at, tz),
        "status": booking.status,
        "price": money(booking.price),
        "price_breakdown": booking.price_breakdown or {},
        "notes": booking.notes,
        "created_by": booking.created_by,
        "cancellation_reason": booking.cancellation_reason,
    }


def get_booking(db: Session, business_id: str, booking_id: str) -> Booking | None:
    """Fetch by id or by human reference — the agent may have either."""
    booking = db.get(Booking, booking_id)
    if booking is None:
        booking = db.scalars(
            select(Booking).where(Booking.business_id == business_id, Booking.reference == booking_id)
        ).first()
    if booking is None or booking.business_id != business_id:
        return None
    return booking


def _resolve_start(business: Business, day: str, start_time: str) -> datetime:
    """Combine a business-local date and HH:MM into a UTC instant."""
    naive = datetime.combine(date.fromisoformat(day), parse_hhmm(start_time))
    return to_utc(naive, business.timezone)


def _capacity_free(
    db: Session, business: Business, start: datetime, end: datetime, exclude_booking_id: str | None = None
) -> tuple[bool, int]:
    concurrent = sum(
        1
        for b in _bookings_on(db, business.id, start, end)
        if b.id != exclude_booking_id and overlaps(start, end, b.starts_at, b.ends_at)
    )
    return concurrent < business.concurrent_capacity, concurrent


def create_booking(
    db: Session,
    business_id: str,
    customer_id: str,
    service_id: str,
    day: str,
    start_time: str,
    notes: str | None = None,
    price: float | None = None,
    price_breakdown: dict | None = None,
    created_by: str = "agent",
) -> dict:
    """Put a job on the calendar, re-checking capacity at write time."""
    business = get_business(db, business_id)
    service = get_service(db, business_id, service_id)
    if service is None:
        return {"ok": False, "error": f"unknown service_id {service_id!r}"}

    try:
        starts_at = _resolve_start(business, day, start_time)
    except ValueError as exc:
        return {"ok": False, "error": f"could not read date/time: {exc}"}

    ends_at = starts_at + timedelta(minutes=service.duration_minutes)

    if starts_at <= datetime.now(UTC):
        return {
            "ok": False,
            "error": "that slot is in the past",
            "requested": local_iso(starts_at, business.timezone),
        }

    window = _day_window(business, to_local(starts_at, business.timezone).date())
    if window is None or not (window[0] <= starts_at and ends_at <= window[1]):
        return {
            "ok": False,
            "error": "outside opening hours",
            "requested": local_iso(starts_at, business.timezone),
        }

    free, concurrent = _capacity_free(db, business, starts_at, ends_at)
    if not free:
        return {
            "ok": False,
            "error": "slot is full",
            "concurrent_bookings": concurrent,
            "capacity": business.concurrent_capacity,
        }

    if price is None:
        price = money(service.base_price)

    booking = Booking(
        business_id=business_id,
        customer_id=customer_id,
        service_id=service_id,
        reference=next_reference(db, business),
        starts_at=starts_at,
        ends_at=ends_at,
        status=BookingStatus.CONFIRMED,
        price=price,
        price_breakdown=price_breakdown or {},
        notes=notes,
        created_by=created_by,
    )
    db.add(booking)
    db.flush()
    return {
        "ok": True,
        "created": True,
        "currency": business.currency,
        **booking_dict(db, booking, business.timezone),
    }


def reschedule_booking(
    db: Session, business_id: str, booking_id: str, day: str, start_time: str, reason: str | None = None
) -> dict:
    """Move an existing booking, honouring the rescheduling notice policy."""
    from app.services.business import get_policy

    business = get_business(db, business_id)
    booking = get_booking(db, business_id, booking_id)
    if booking is None:
        return {"ok": False, "error": f"unknown booking {booking_id!r}"}
    if booking.status in (BookingStatus.CANCELLED, BookingStatus.COMPLETED):
        return {"ok": False, "error": f"booking is {booking.status} and cannot be moved"}

    service = db.get(Service, booking.service_id)
    try:
        new_start = _resolve_start(business, day, start_time)
    except ValueError as exc:
        return {"ok": False, "error": f"could not read date/time: {exc}"}
    new_end = new_start + timedelta(minutes=service.duration_minutes)

    rules = get_policy(db, business_id, "rescheduling")["rules"]
    min_notice = int(rules.get("min_notice_hours", 0))
    hours_until_original = (booking.starts_at - datetime.now(UTC)).total_seconds() / 3600
    if hours_until_original < min_notice:
        return {
            "ok": False,
            "error": "inside the minimum notice window",
            "min_notice_hours": min_notice,
            "hours_until_original": round(hours_until_original, 1),
        }

    if new_start <= datetime.now(UTC):
        return {"ok": False, "error": "that slot is in the past"}

    window = _day_window(business, to_local(new_start, business.timezone).date())
    if window is None or not (window[0] <= new_start and new_end <= window[1]):
        return {"ok": False, "error": "outside opening hours"}

    free, concurrent = _capacity_free(db, business, new_start, new_end, exclude_booking_id=booking.id)
    if not free:
        return {"ok": False, "error": "slot is full", "concurrent_bookings": concurrent}

    previous = local_iso(booking.starts_at, business.timezone)
    booking.starts_at = new_start
    booking.ends_at = new_end
    if reason:
        booking.notes = (
            f"{booking.notes}\nRescheduled: {reason}".strip() if booking.notes else f"Rescheduled: {reason}"
        )
    db.flush()

    return {
        "ok": True,
        "rescheduled": True,
        "previous_starts_at": previous,
        **booking_dict(db, booking, business.timezone),
    }


def cancel_booking(db: Session, business_id: str, booking_id: str, reason: str | None = None) -> dict:
    """Cancel a booking and report the fee the cancellation policy implies."""
    from app.services.business import get_policy

    business = get_business(db, business_id)
    booking = get_booking(db, business_id, booking_id)
    if booking is None:
        return {"ok": False, "error": f"unknown booking {booking_id!r}"}
    if booking.status == BookingStatus.CANCELLED:
        return {"ok": False, "error": "booking is already cancelled"}

    rules = get_policy(db, business_id, "cancellation")["rules"]
    free_hours = int(rules.get("free_cancellation_hours", 0))
    fee_percent = float(rules.get("late_cancellation_fee_percent", 0))
    hours_notice = (booking.starts_at - datetime.now(UTC)).total_seconds() / 3600
    late = hours_notice < free_hours
    fee = money(float(booking.price) * fee_percent / 100) if late else 0.0

    booking.status = BookingStatus.CANCELLED
    booking.cancellation_reason = reason
    db.flush()

    return {
        "ok": True,
        "cancelled": True,
        "hours_notice": round(hours_notice, 1),
        "free_cancellation_hours": free_hours,
        "late_cancellation": late,
        "cancellation_fee": fee,
        "currency": business.currency,
        **booking_dict(db, booking, business.timezone),
    }


def list_bookings(
    db: Session, business_id: str, upcoming_only: bool = False, limit: int = 50
) -> list[dict]:
    stmt = select(Booking).where(Booking.business_id == business_id)
    if upcoming_only:
        stmt = stmt.where(Booking.starts_at >= datetime.now(UTC), Booking.status.in_(ACTIVE_STATUSES))
    stmt = stmt.order_by(Booking.starts_at.asc() if upcoming_only else Booking.starts_at.desc()).limit(limit)
    tz = get_business(db, business_id).timezone
    return [booking_dict(db, b, tz) for b in db.scalars(stmt).all()]
