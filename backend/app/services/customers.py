"""Customer lookup and history."""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.enums import ApprovalStatus
from app.db.models import Approval, Booking, Conversation, Customer, Message, Refund
from app.services.business import get_business
from app.services.common import local_iso, money


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def find_customer(
    db: Session,
    business_id: str,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> dict:
    """Locate a customer by any identifier the message happened to contain.

    Matching is deliberately ordered strongest-first (email, then phone, then
    name) and reports which identifier matched, so the agent can tell the
    difference between a confident hit and a fuzzy one.
    """
    base = select(Customer).where(Customer.business_id == business_id)

    if email:
        row = db.scalars(base.where(func.lower(Customer.email) == email.strip().lower())).first()
        if row:
            return {"found": True, "matched_on": "email", **_customer_dict(row)}

    if phone:
        digits = _digits(phone)[-9:]
        if digits:
            rows = db.scalars(base.where(Customer.phone.isnot(None))).all()
            for row in rows:
                if _digits(row.phone or "").endswith(digits):
                    return {"found": True, "matched_on": "phone", **_customer_dict(row)}

    if name:
        needle = name.strip().lower()
        exact = db.scalars(base.where(func.lower(Customer.name) == needle)).first()
        if exact:
            return {"found": True, "matched_on": "name", **_customer_dict(exact)}
        partial = db.scalars(
            base.where(
                or_(
                    func.lower(Customer.name).like(f"%{needle}%"),
                    func.lower(Customer.name).like(f"{needle.split()[0]}%"),
                )
            )
        ).all()
        if len(partial) == 1:
            return {"found": True, "matched_on": "name_partial", **_customer_dict(partial[0])}
        if len(partial) > 1:
            return {
                "found": False,
                "reason": "ambiguous_name",
                "candidates": [{"customer_id": c.id, "name": c.name, "email": c.email} for c in partial],
            }

    return {"found": False, "reason": "no_match"}


def _customer_dict(customer: Customer) -> dict:
    return {
        "customer_id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone,
        "address": customer.address,
        "preferences": customer.preferences or {},
        "lifetime_value": money(customer.lifetime_value),
        "notes": customer.notes,
    }


def get_customer(db: Session, business_id: str, customer_id: str) -> Customer | None:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.business_id != business_id:
        return None
    return customer


def get_customer_history(db: Session, business_id: str, customer_id: str, limit: int = 10) -> dict:
    """Everything the agent needs to judge a customer's situation in one call."""
    customer = get_customer(db, business_id, customer_id)
    if customer is None:
        return {"ok": False, "error": f"unknown customer_id {customer_id!r}"}

    tz = get_business(db, business_id).timezone

    bookings = db.scalars(
        select(Booking)
        .where(Booking.customer_id == customer_id)
        .order_by(Booking.starts_at.desc())
        .limit(limit)
    ).all()

    conversations = db.scalars(
        select(Conversation)
        .where(Conversation.customer_id == customer_id)
        .order_by(Conversation.last_message_at.desc().nullslast())
        .limit(limit)
    ).all()

    refunds = db.scalars(
        select(Refund).where(Refund.customer_id == customer_id).order_by(Refund.created_at.desc())
    ).all()

    open_approvals = db.scalars(
        select(Approval).where(
            Approval.business_id == business_id, Approval.status == ApprovalStatus.PENDING
        )
    ).all()

    return {
        "ok": True,
        **_customer_dict(customer),
        "booking_count": len(bookings),
        "bookings": [
            {
                "booking_id": b.id,
                "reference": b.reference,
                "service_id": b.service_id,
                "starts_at": local_iso(b.starts_at, tz),
                "status": b.status,
                "price": money(b.price),
            }
            for b in bookings
        ],
        "conversations": [
            {
                "conversation_id": c.id,
                "subject": c.subject,
                "status": c.status,
                "channel": c.channel,
                "last_message_at": local_iso(c.last_message_at, tz),
                "follow_up_count": c.follow_up_count,
            }
            for c in conversations
        ],
        "refund_history": [
            {
                "refund_id": r.id,
                "booking_id": r.booking_id,
                "amount": money(r.amount),
                "status": r.status,
                "created_at": local_iso(r.created_at, tz),
            }
            for r in refunds
        ],
        "total_refunded": money(sum(float(r.amount) for r in refunds)),
        "pending_approvals_for_business": len(open_approvals),
    }


def update_customer(db: Session, business_id: str, customer_id: str, fields: dict) -> dict:
    """Update a whitelisted set of customer fields."""
    customer = get_customer(db, business_id, customer_id)
    if customer is None:
        return {"ok": False, "error": f"unknown customer_id {customer_id!r}"}

    allowed = {"name", "email", "phone", "address", "notes", "preferences"}
    rejected = sorted(set(fields) - allowed)
    for key, value in fields.items():
        if key in allowed:
            setattr(customer, key, value)
    db.flush()

    return {
        "ok": True,
        "updated": sorted(set(fields) & allowed),
        "rejected": rejected,
        **_customer_dict(customer),
    }


def create_customer(
    db: Session,
    business_id: str,
    name: str,
    email: str | None = None,
    phone: str | None = None,
    address: str | None = None,
) -> dict:
    customer = Customer(
        business_id=business_id, name=name, email=email, phone=phone, address=address, preferences={}
    )
    db.add(customer)
    db.flush()
    return {"ok": True, "created": True, **_customer_dict(customer)}


def latest_inbound_message(db: Session, conversation_id: str) -> Message | None:
    return db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.direction == "inbound")
        .order_by(Message.sent_at.desc())
    ).first()
