"""Booking tools."""

from strands import tool

from app.db.session import session_scope
from app.services import bookings as service
from app.tools._context import current


@tool
def check_availability(
    service_id: str,
    date: str,
    preferred_period: str | None = None,
) -> dict:
    """Find the slots a service can actually be delivered in on a given day.

    Always call this before creating or moving a booking — it accounts for opening
    hours, how many jobs can run at once, and what is already on the calendar. Do
    not offer a customer a time this has not returned.

    Args:
        service_id: The service to schedule, from `get_service_catalog`.
        date: The day to check, as `YYYY-MM-DD`.
        preferred_period: Optional `morning`, `afternoon` or `evening` to narrow it.

    Returns:
        `available`, a list of `slots` with local start times, and a `message`
        explaining any day that has none.
    """
    ctx = current()
    with session_scope() as db:
        return service.check_availability(
            db, ctx.business_id, service_id, date, preferred_period=preferred_period
        )


@tool
def get_booking(booking_id: str) -> dict:
    """Retrieve one booking by id or by its customer-facing reference.

    Args:
        booking_id: Either an internal id like `book_1a2b3c4d` or a reference the
            customer would quote, like `BH-1042`.

    Returns:
        The booking, including price, status and times in the business's timezone.
    """
    ctx = current()
    with session_scope() as db:
        booking = service.get_booking(db, ctx.business_id, booking_id)
        if booking is None:
            return {"ok": False, "error": f"no booking matches {booking_id!r}"}
        return {"ok": True, **service.booking_dict(db, booking)}


@tool
def create_booking(
    customer_id: str,
    service_id: str,
    date: str,
    start_time: str,
    price: float | None = None,
    notes: str | None = None,
) -> dict:
    """Put a job on the calendar.

    Only use a `start_time` that `check_availability` returned for that day, and
    pass the `price` you got from `calculate_price` so the customer is charged what
    you quoted. Capacity is re-checked here, so a slot can still be refused if it
    filled up meanwhile.

    Args:
        customer_id: Who the booking is for.
        service_id: What is being booked.
        date: The day, as `YYYY-MM-DD`.
        start_time: Local start time as `HH:MM`.
        price: The quoted price. Defaults to the service's list price.
        notes: Anything the crew needs to know, e.g. access instructions.

    Returns:
        The created booking with its reference, or `ok: false` with the reason.
    """
    ctx = current()
    with session_scope() as db:
        return service.create_booking(
            db,
            ctx.business_id,
            customer_id=customer_id,
            service_id=service_id,
            day=date,
            start_time=start_time,
            price=price,
            notes=notes,
            created_by="agent",
        )


@tool
def reschedule_booking(
    booking_id: str,
    date: str,
    start_time: str,
    reason: str | None = None,
) -> dict:
    """Move an existing booking to a new day and time.

    Check the new slot with `check_availability` first. The rescheduling policy is
    enforced here, so a move can be refused for being inside the notice window or
    sent for approval if the booking has been moved too many times already.

    Args:
        booking_id: The booking to move, by id or reference.
        date: New day, as `YYYY-MM-DD`.
        start_time: New local start time as `HH:MM`.
        reason: Why it is moving — this goes on the record.

    Returns:
        The updated booking and its previous start time.
    """
    ctx = current()
    with session_scope() as db:
        return service.reschedule_booking(
            db, ctx.business_id, booking_id, day=date, start_time=start_time, reason=reason
        )


@tool
def cancel_booking(booking_id: str, reason: str) -> dict:
    """Cancel a booking and report any late-cancellation fee.

    The cancellation policy decides whether a fee applies. Inside the free window
    the owner is asked before this goes through.

    Args:
        booking_id: The booking to cancel, by id or reference.
        reason: Why it is being cancelled.

    Returns:
        The cancelled booking, the notice given, and the fee the policy implies.
    """
    ctx = current()
    with session_scope() as db:
        return service.cancel_booking(db, ctx.business_id, booking_id, reason=reason)
