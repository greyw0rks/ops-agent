"""Business configuration tools: catalogue, policies, pricing."""

from strands import tool

from app.db.session import session_scope
from app.services import business as service
from app.tools._context import current


@tool
def get_service_catalog() -> dict:
    """List everything the business sells, with list prices and job durations.

    Call this to turn what a customer wrote ("a deep clean") into a real
    `service_id` before checking availability or quoting.

    Returns:
        The business name, currency, timezone, and every active service.
    """
    ctx = current()
    with session_scope() as db:
        return service.get_service_catalog(db, ctx.business_id)


@tool
def get_business_policy(policy_type: str) -> dict:
    """Read one of the owner's operating policies.

    Read the relevant policy before you commit to anything a customer asks for —
    a refund, a discount, a late cancellation, a second reschedule. The policy is
    also what you should quote when explaining a decision to a customer.

    Args:
        policy_type: One of `refund`, `discount`, `cancellation`, `rescheduling`.

    Returns:
        The policy rules, and where they came from (the owner's config or the
        platform default).
    """
    ctx = current()
    with session_scope() as db:
        return service.get_policy(db, ctx.business_id, policy_type)


@tool
def calculate_price(
    service_id: str,
    quantities: dict | None = None,
    customer_id: str | None = None,
) -> dict:
    """Price a job from the catalogue.

    Use this rather than doing the arithmetic yourself, so the quote you send and
    the price on the booking are the same number and can be explained line by line.

    Args:
        service_id: The service being quoted.
        quantities: Countable extras the customer mentioned, e.g.
            `{"bedrooms": 3, "bathrooms": 2}`. Only extras the service actually
            charges for are applied; the rest are ignored.
        customer_id: Optional, so loyalty context can be flagged.

    Returns:
        `price`, `currency`, and a `breakdown` of how it was reached.
    """
    ctx = current()
    with session_scope() as db:
        return service.calculate_price(
            db, ctx.business_id, service_id, quantities=quantities, customer_id=customer_id
        )


@tool
def find_service(name: str) -> dict:
    """Match a service by the words a customer used.

    A fallback for when `get_service_catalog` did not make the mapping obvious —
    "move out clean" should still reach "Move-out Cleaning".

    Args:
        name: The service as the customer described it.

    Returns:
        The matching service, or `found: false` if nothing is close enough.
    """
    ctx = current()
    with session_scope() as db:
        match = service.find_service_by_name(db, ctx.business_id, name)
        if match is None:
            return {"found": False, "query": name}
        return {
            "found": True,
            "service_id": match.id,
            "name": match.name,
            "base_price": float(match.base_price),
            "duration_minutes": match.duration_minutes,
        }
