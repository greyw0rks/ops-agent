"""Business configuration: the service catalogue, the operating policies, and pricing.

The policy rows returned here are the ones the risk engine enforces. Pricing lives
in the service layer rather than in the prompt so that a quote is reproducible.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Business, BusinessPolicy, Customer, Service
from app.services.common import money

DEFAULT_POLICIES: dict[str, dict] = {
    "refund": {
        "auto_approve_below": 5000,
        "approval_required_below": 60000,
        "manual_review_above": 60000,
        "window_days": 14,
    },
    "discount": {
        "auto_approve_percent": 10,
        "approval_required_percent": 25,
        "manual_review_above_percent": 25,
    },
    "cancellation": {
        "free_cancellation_hours": 24,
        "late_cancellation_fee_percent": 30,
    },
    "rescheduling": {
        "free_reschedules": 2,
        "min_notice_hours": 4,
    },
}


class BusinessNotFound(Exception):
    pass


def get_business(db: Session, business_id: str) -> Business:
    business = db.get(Business, business_id)
    if business is None:
        raise BusinessNotFound(business_id)
    return business


def get_default_business(db: Session) -> Business:
    """Single-tenant convenience for the demo deployment."""
    business = db.scalars(select(Business).order_by(Business.created_at)).first()
    if business is None:
        raise BusinessNotFound("no business configured")
    return business


def get_service(db: Session, business_id: str, service_id: str) -> Service | None:
    service = db.get(Service, service_id)
    if service is None or service.business_id != business_id:
        return None
    return service


def find_service_by_name(db: Session, business_id: str, name: str) -> Service | None:
    """Loose name match so the agent can pass what the customer actually wrote."""
    needle = name.strip().lower()
    services = db.scalars(
        select(Service).where(Service.business_id == business_id, Service.active.is_(True))
    ).all()
    for service in services:
        if service.name.lower() == needle:
            return service
    for service in services:
        if needle in service.name.lower() or service.name.lower() in needle:
            return service
    # Fall back to word overlap: "deep clean" should still reach "Deep Cleaning".
    needle_words = {w for w in needle.split() if len(w) > 3}
    best: tuple[int, Service | None] = (0, None)
    for service in services:
        overlap = len({w for w in service.name.lower().split() if len(w) > 3} & needle_words)
        if overlap > best[0]:
            best = (overlap, service)
    return best[1]


def get_service_catalog(db: Session, business_id: str) -> dict:
    business = get_business(db, business_id)
    services = db.scalars(
        select(Service).where(Service.business_id == business_id, Service.active.is_(True))
    ).all()
    return {
        "business_name": business.name,
        "currency": business.currency,
        "timezone": business.timezone,
        "services": [
            {
                "service_id": s.id,
                "name": s.name,
                "description": s.description,
                "base_price": money(s.base_price),
                "duration_minutes": s.duration_minutes,
                "price_modifiers": s.price_modifiers or {},
            }
            for s in services
        ],
    }


def get_policy(db: Session, business_id: str, policy_type: str) -> dict:
    """Return one operating policy, falling back to the platform default."""
    row = db.scalars(
        select(BusinessPolicy).where(
            BusinessPolicy.business_id == business_id,
            BusinessPolicy.policy_type == policy_type,
        )
    ).first()
    if row is None:
        rules = DEFAULT_POLICIES.get(policy_type)
        if rules is None:
            return {"policy_type": policy_type, "found": False, "rules": {}}
        return {"policy_type": policy_type, "found": True, "source": "default", "rules": rules}
    return {
        "policy_type": policy_type,
        "found": True,
        "source": "business",
        "rules": row.rules or {},
        "summary": row.summary,
    }


def get_all_policies(db: Session, business_id: str) -> dict[str, dict]:
    rows = db.scalars(select(BusinessPolicy).where(BusinessPolicy.business_id == business_id)).all()
    policies = {k: dict(v) for k, v in DEFAULT_POLICIES.items()}
    for row in rows:
        policies[row.policy_type] = row.rules or {}
    return policies


def calculate_price(
    db: Session,
    business_id: str,
    service_id: str,
    quantities: dict | None = None,
    customer_id: str | None = None,
) -> dict:
    """Price a job from the catalogue and the service's declared modifiers.

    `quantities` carries countable extras, e.g. {"bedrooms": 3, "bathrooms": 2}.
    Only keys the service declares in `price_modifiers` are chargeable, so the
    agent cannot invent a line item.
    """
    business = get_business(db, business_id)
    service = get_service(db, business_id, service_id)
    if service is None:
        return {"ok": False, "error": f"unknown service_id {service_id!r}"}

    modifiers = service.price_modifiers or {}
    breakdown = [{"label": service.name, "amount": money(service.base_price)}]
    total = money(service.base_price)

    # The base price already includes one unit of each modifier.
    for key, unit_price in modifiers.items():
        requested = (quantities or {}).get(key)
        if not requested or int(requested) <= 1:
            continue
        extra_units = int(requested) - 1
        amount = money(float(unit_price) * extra_units)
        breakdown.append({"label": f"{extra_units} extra {key}", "amount": amount})
        total = money(total + amount)

    loyalty_note = None
    if customer_id:
        customer = db.get(Customer, customer_id)
        if customer is not None and float(customer.lifetime_value or 0) >= 50000:
            loyalty_note = "Returning customer — eligible for a loyalty discount if the owner offers one."

    return {
        "ok": True,
        "service_id": service.id,
        "service_name": service.name,
        "currency": business.currency,
        "price": total,
        "duration_minutes": service.duration_minutes,
        "breakdown": breakdown,
        "note": loyalty_note,
    }
