"""Money movement: refunds, discounts, supplier invoices.

Every function here re-asserts the hard limits from the business policy even
though the risk engine has already gated the call. The gate stops the agent from
proposing something out of bounds; these checks mean a bug in the gate still
cannot move money past the ceiling the owner set.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import BookingStatus, InvoiceStatus, RefundStatus
from app.db.models import Booking, Refund, SupplierInvoice
from app.services.bookings import get_booking
from app.services.business import get_business, get_policy
from app.services.common import local_iso, money


class PolicyViolation(Exception):
    """Raised when a write would breach a hard policy ceiling."""


def refunded_total(db: Session, booking_id: str) -> float:
    rows = db.scalars(select(Refund).where(Refund.booking_id == booking_id)).all()
    return money(sum(float(r.amount) for r in rows if r.status != RefundStatus.REJECTED))


def issue_refund(
    db: Session,
    business_id: str,
    booking_id: str,
    amount: float,
    reason: str | None = None,
    approval_id: str | None = None,
    agent_run_id: str | None = None,
) -> dict:
    """Record a refund against a booking."""
    business = get_business(db, business_id)
    booking = get_booking(db, business_id, booking_id)
    if booking is None:
        return {"ok": False, "error": f"unknown booking {booking_id!r}"}

    amount = money(amount)
    if amount <= 0:
        return {"ok": False, "error": "refund amount must be positive"}

    already = refunded_total(db, booking.id)
    if amount + already > money(booking.price):
        return {
            "ok": False,
            "error": "refund exceeds what was paid for this booking",
            "booking_price": money(booking.price),
            "already_refunded": already,
            "requested": amount,
        }

    rules = get_policy(db, business_id, "refund")["rules"]
    ceiling = float(rules.get("manual_review_above", 0) or 0)
    if ceiling and amount > ceiling and approval_id is None:
        raise PolicyViolation(
            f"refund of {amount} exceeds the manual-review ceiling of {ceiling} and has no approval"
        )

    refund = Refund(
        business_id=business_id,
        booking_id=booking.id,
        customer_id=booking.customer_id,
        amount=amount,
        reason=reason,
        status=RefundStatus.PAID,
        approval_id=approval_id,
        agent_run_id=agent_run_id,
    )
    db.add(refund)

    if amount >= money(booking.price):
        booking.status = BookingStatus.CANCELLED
        booking.cancellation_reason = reason or "refunded in full"
    db.flush()

    return {
        "ok": True,
        "refund_id": refund.id,
        "booking_id": booking.id,
        "booking_reference": booking.reference,
        "customer_id": booking.customer_id,
        "amount": amount,
        "currency": business.currency,
        "total_refunded_on_booking": refunded_total(db, booking.id),
        "authorised_by_approval": approval_id,
        "status": refund.status,
    }


def apply_discount(
    db: Session,
    business_id: str,
    booking_id: str,
    percent: float,
    reason: str | None = None,
    approval_id: str | None = None,
) -> dict:
    """Reduce a booking's price by a percentage."""
    business = get_business(db, business_id)
    booking = get_booking(db, business_id, booking_id)
    if booking is None:
        return {"ok": False, "error": f"unknown booking {booking_id!r}"}

    if percent <= 0 or percent >= 100:
        return {"ok": False, "error": "discount percent must be between 0 and 100"}

    rules = get_policy(db, business_id, "discount")["rules"]
    ceiling = float(rules.get("manual_review_above_percent", 0) or 0)
    if ceiling and percent > ceiling and approval_id is None:
        raise PolicyViolation(
            f"discount of {percent}% exceeds the {ceiling}% ceiling and has no approval"
        )

    original = money(booking.price)
    discount_amount = money(original * percent / 100)
    booking.price = money(original - discount_amount)
    breakdown = dict(booking.price_breakdown or {})
    breakdown.setdefault("adjustments", []).append(
        {"type": "discount", "percent": percent, "amount": -discount_amount, "reason": reason}
    )
    booking.price_breakdown = breakdown
    db.flush()

    return {
        "ok": True,
        "booking_id": booking.id,
        "booking_reference": booking.reference,
        "percent": percent,
        "discount_amount": discount_amount,
        "original_price": original,
        "new_price": money(booking.price),
        "currency": business.currency,
        "authorised_by_approval": approval_id,
    }


def record_supplier_invoice(
    db: Session,
    business_id: str,
    supplier_name: str,
    amount: float,
    reference: str | None = None,
    issued_at: datetime | None = None,
    due_at: datetime | None = None,
    document_key: str | None = None,
    extracted: dict | None = None,
    agent_run_id: str | None = None,
) -> dict:
    """File a supplier invoice, refusing an exact duplicate."""
    business = get_business(db, business_id)

    if reference:
        duplicate = db.scalars(
            select(SupplierInvoice).where(
                SupplierInvoice.business_id == business_id,
                SupplierInvoice.reference == reference,
                SupplierInvoice.supplier_name == supplier_name,
            )
        ).first()
        if duplicate:
            return {
                "ok": False,
                "error": "duplicate_invoice",
                "existing_invoice_id": duplicate.id,
                "reference": reference,
                "amount": money(duplicate.amount),
            }

    invoice = SupplierInvoice(
        business_id=business_id,
        supplier_name=supplier_name,
        reference=reference,
        amount=money(amount),
        issued_at=issued_at,
        due_at=due_at,
        status=InvoiceStatus.RECEIVED,
        document_key=document_key,
        extracted=extracted or {},
        agent_run_id=agent_run_id,
    )
    db.add(invoice)
    db.flush()

    return {
        "ok": True,
        "invoice_id": invoice.id,
        "supplier_name": supplier_name,
        "reference": reference,
        "amount": money(invoice.amount),
        "currency": business.currency,
        "due_at": local_iso(invoice.due_at, business.timezone),
        "status": invoice.status,
    }


def list_invoices(db: Session, business_id: str, limit: int = 50) -> list[dict]:
    tz = get_business(db, business_id).timezone
    rows = db.scalars(
        select(SupplierInvoice)
        .where(SupplierInvoice.business_id == business_id)
        .order_by(SupplierInvoice.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "invoice_id": r.id,
            "supplier_name": r.supplier_name,
            "reference": r.reference,
            "amount": money(r.amount),
            "status": r.status,
            "due_at": local_iso(r.due_at, tz),
            "received_at": local_iso(r.created_at, tz),
        }
        for r in rows
    ]


def list_refunds(db: Session, business_id: str, limit: int = 50) -> list[dict]:
    tz = get_business(db, business_id).timezone
    rows = db.scalars(
        select(Refund)
        .where(Refund.business_id == business_id)
        .order_by(Refund.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "refund_id": r.id,
            "booking_id": r.booking_id,
            "customer_id": r.customer_id,
            "amount": money(r.amount),
            "status": r.status,
            "reason": r.reason,
            "approval_id": r.approval_id,
            "created_at": local_iso(r.created_at, tz),
        }
        for r in rows
    ]


def now_utc() -> datetime:
    return datetime.now(UTC)


def booking_price(db: Session, booking_id: str) -> float:
    booking = db.get(Booking, booking_id)
    return money(booking.price) if booking else 0.0
