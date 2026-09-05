"""Customer tools."""

from strands import tool

from app.db.session import session_scope
from app.services import customers as service
from app.tools._context import current


@tool
def find_customer(
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> dict:
    """Look up a customer by name, email address, or phone number.

    Call this first whenever a message comes in, so the rest of your work is
    attached to the right person. Pass whatever identifiers the message gave you;
    the strongest one wins. If the result reports `ambiguous_name`, ask which
    person is meant rather than guessing.

    Args:
        name: Full or partial name as the customer wrote it.
        email: Email address, if known.
        phone: Phone number in any format.

    Returns:
        `found` plus the customer profile, or `found: false` with a reason.
    """
    ctx = current()
    with session_scope() as db:
        return service.find_customer(db, ctx.business_id, name=name, email=email, phone=phone)


@tool
def get_customer_history(customer_id: str) -> dict:
    """Retrieve a customer's bookings, conversations and refund history.

    Use this before making any judgement call about a customer — a complaint from
    someone on their first booking is a different situation from one who has been
    refunded twice already.

    Args:
        customer_id: The customer's id, e.g. `cus_1a2b3c4d`.

    Returns:
        Profile, recent bookings, conversation threads, and total refunded to date.
    """
    ctx = current()
    with session_scope() as db:
        return service.get_customer_history(db, ctx.business_id, customer_id)


@tool
def create_customer(
    name: str,
    email: str | None = None,
    phone: str | None = None,
    address: str | None = None,
) -> dict:
    """Add a customer who is not on file yet.

    Only call this after `find_customer` has come back empty, so you do not create
    a duplicate record.

    Args:
        name: The customer's name.
        email: Email address, if given.
        phone: Phone number, if given.
        address: Service address, if given.

    Returns:
        The new customer record.
    """
    ctx = current()
    with session_scope() as db:
        return service.create_customer(
            db, ctx.business_id, name=name, email=email, phone=phone, address=address
        )


@tool
def update_customer(customer_id: str, fields: dict) -> dict:
    """Update a customer's details or standing preferences.

    Use this when a customer tells you something durable — a new address, a phone
    number, or a preference such as always wanting afternoon slots.

    Args:
        customer_id: The customer's id.
        fields: Any of `name`, `email`, `phone`, `address`, `notes`, `preferences`.
            Anything else is ignored and reported back in `rejected`.

    Returns:
        The updated record and the list of fields actually applied.
    """
    ctx = current()
    with session_scope() as db:
        return service.update_customer(db, ctx.business_id, customer_id, fields)
