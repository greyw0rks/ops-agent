"""Seed the demo business.

Creates BrightHome Services with a service catalogue, operating policies, a handful
of customers with real history, and the two open threads the demo walks through:
a booking request and a complaint.

Idempotent: running it again wipes the business's rows and rebuilds them.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.db.enums import (
    BookingStatus,
    ConversationStatus,
    MessageAuthor,
    MessageDirection,
    TaskPriority,
)
from app.db.models import (
    DEFAULT_OPENING_HOURS,
    AgentRun,
    Approval,
    Booking,
    Business,
    BusinessPolicy,
    Conversation,
    Customer,
    Message,
    Refund,
    Service,
    SupplierInvoice,
    Task,
)
from app.db.session import session_scope
from app.services.business import DEFAULT_POLICIES

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("seed")

BUSINESS_NAME = "BrightHome Services"

SERVICES = [
    ("Standard Home Cleaning", "Regular clean of a furnished home.", 7500, 120, {"bedrooms": 1500}),
    ("Deep Cleaning", "Full deep clean including appliances and skirting.", 15000, 240, {"bedrooms": 2500}),
    ("Move-out Cleaning", "End-of-tenancy clean to letting-agent standard.", 25000, 300, {"bedrooms": 3500}),
    ("Office Cleaning", "After-hours commercial clean.", 12000, 180, {"rooms": 2000}),
]

CUSTOMERS = [
    {
        "name": "Sarah Johnson",
        "email": "sarah.johnson@example.com",
        "phone": "+2348031114455",
        "address": "14 Adeola Odeku St, Victoria Island, Lagos",
        "preferences": {"preferred_period": "afternoon", "pets": "one cat"},
        "lifetime_value": 52500,
    },
    {
        "name": "Daniel Okoro",
        "email": "daniel.okoro@example.com",
        "phone": "+2348022223311",
        "address": "7 Glover Rd, Ikoyi, Lagos",
        "preferences": {"preferred_period": "morning"},
        "lifetime_value": 15000,
    },
    {
        "name": "Amaka Eze",
        "email": "amaka.eze@example.com",
        "phone": "+2347066668899",
        "address": "22 Bourdillon Rd, Ikoyi, Lagos",
        "preferences": {},
        "lifetime_value": 7500,
    },
]


def wipe(db, business_id: str) -> None:
    """Remove everything belonging to the demo business, children first."""
    conversation_ids = [
        c.id for c in db.scalars(select(Conversation).where(Conversation.business_id == business_id)).all()
    ]
    if conversation_ids:
        db.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
    for model in (Approval, Refund, Task, SupplierInvoice, Booking, Conversation, AgentRun):
        db.execute(delete(model).where(model.business_id == business_id))
    for model in (Service, BusinessPolicy, Customer):
        db.execute(delete(model).where(model.business_id == business_id))
    db.flush()


def upsert_business(db) -> Business:
    business = db.scalars(select(Business).where(Business.name == BUSINESS_NAME)).first()
    if business is None:
        business = Business(name=BUSINESS_NAME)
        db.add(business)
    business.industry = "home services"
    business.timezone = "Africa/Lagos"
    business.currency = "NGN"
    business.contact_email = "hello@brighthome.example"
    business.contact_phone = "+2348090001122"
    business.opening_hours = dict(DEFAULT_OPENING_HOURS)
    business.concurrent_capacity = 2
    business.slot_interval_minutes = 60
    db.flush()
    return business


def seed_services(db, business: Business) -> dict[str, Service]:
    created: dict[str, Service] = {}
    for name, description, price, duration, modifiers in SERVICES:
        service = Service(
            business_id=business.id,
            name=name,
            description=description,
            base_price=price,
            duration_minutes=duration,
            price_modifiers=modifiers,
        )
        db.add(service)
        created[name] = service
    db.flush()
    return created


def seed_policies(db, business: Business) -> None:
    summaries = {
        "refund": (
            "Refunds under NGN 5,000 are handled without escalation. Between NGN 5,000 and "
            "NGN 60,000 the owner decides. Above NGN 60,000 the owner handles it personally. "
            "Claims must be raised within 14 days of the job."
        ),
        "discount": "Up to 10% is pre-authorised. 10–25% needs the owner. Above 25% is theirs alone.",
        "cancellation": "Free with 24 hours' notice. Inside that, a 30% fee applies.",
        "rescheduling": "Two moves per booking without asking, minimum 4 hours' notice.",
    }
    for policy_type, rules in DEFAULT_POLICIES.items():
        db.add(
            BusinessPolicy(
                business_id=business.id,
                policy_type=policy_type,
                rules=dict(rules),
                summary=summaries.get(policy_type),
            )
        )
    db.flush()


def seed_customers(db, business: Business) -> dict[str, Customer]:
    created: dict[str, Customer] = {}
    for spec in CUSTOMERS:
        customer = Customer(business_id=business.id, **spec)
        db.add(customer)
        created[spec["name"]] = customer
    db.flush()
    return created


def _at(days: int, hour: int) -> datetime:
    """A time relative to now, on the hour, in UTC."""
    return (datetime.now(UTC) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


def seed_history(db, business: Business, customers: dict, services: dict) -> Booking:
    """Past and future jobs, so the agent has real history to reason about."""
    ref = 1041

    def add_booking(customer, service, when, status, price=None, notes=None, created_by="owner"):
        nonlocal ref
        booking = Booking(
            business_id=business.id,
            customer_id=customer.id,
            service_id=service.id,
            reference=f"BH-{ref}",
            starts_at=when,
            ends_at=when + timedelta(minutes=service.duration_minutes),
            status=status,
            price=price if price is not None else service.base_price,
            notes=notes,
            created_by=created_by,
        )
        ref += 1
        db.add(booking)
        return booking

    # The job Sarah is about to complain about: a deep clean, yesterday.
    complaint_booking = add_booking(
        customers["Sarah Johnson"],
        services["Deep Cleaning"],
        _at(-1, 10),
        BookingStatus.COMPLETED,
        notes="Kitchen and two bathrooms. Cat in the house.",
    )
    add_booking(
        customers["Sarah Johnson"],
        services["Standard Home Cleaning"],
        _at(-21, 14),
        BookingStatus.COMPLETED,
    )
    add_booking(
        customers["Daniel Okoro"],
        services["Office Cleaning"],
        _at(2, 18),
        BookingStatus.CONFIRMED,
        notes="Reception and two meeting rooms.",
    )
    add_booking(
        customers["Amaka Eze"],
        services["Standard Home Cleaning"],
        _at(1, 9),
        BookingStatus.CONFIRMED,
    )
    db.flush()
    return complaint_booking


def seed_conversations(db, business: Business, customers: dict, booking: Booking) -> dict:
    """The two live threads the demo drives, plus one stale quote to chase."""
    threads: dict[str, Conversation] = {}

    def thread(customer, subject, body, *, hours_ago: float, status, follow_up_days=None, outbound=None):
        conversation = Conversation(
            business_id=business.id,
            customer_id=customer.id if customer else None,
            channel="email",
            subject=subject,
            status=status,
        )
        db.add(conversation)
        db.flush()
        sent_at = datetime.now(UTC) - timedelta(hours=hours_ago)
        db.add(
            Message(
                conversation_id=conversation.id,
                direction=MessageDirection.INBOUND,
                author=MessageAuthor.CUSTOMER,
                body=body,
                sent_at=sent_at,
            )
        )
        last = sent_at
        if outbound:
            last = sent_at + timedelta(minutes=12)
            db.add(
                Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.OUTBOUND,
                    author=MessageAuthor.AGENT,
                    body=outbound,
                    sent_at=last,
                )
            )
        conversation.last_message_at = last
        if follow_up_days is not None:
            conversation.follow_up_due_at = last + timedelta(days=follow_up_days)
        db.flush()
        return conversation

    threads["booking"] = thread(
        customers["Amaka Eze"],
        "Cleaning next weekend",
        "Hi, I'd like to book a standard cleaning for my 3-bedroom flat on Saturday afternoon "
        "if you have anything free. Amaka.",
        hours_ago=0.2,
        status=ConversationStatus.AWAITING_BUSINESS,
    )

    threads["complaint"] = thread(
        customers["Sarah Johnson"],
        f"Yesterday's deep clean ({booking.reference})",
        "I'm really disappointed with yesterday's deep clean. The oven wasn't touched and there "
        "was still dust on the skirting in both bedrooms. I paid for a deep clean and it wasn't "
        "one. I'd like a refund.",
        hours_ago=1,
        status=ConversationStatus.AWAITING_BUSINESS,
    )

    threads["quote"] = thread(
        customers["Daniel Okoro"],
        "Quote for move-out clean",
        "Can you give me a price for a move-out clean on a 2-bedroom in Ikoyi?",
        hours_ago=96,
        status=ConversationStatus.AWAITING_CUSTOMER,
        follow_up_days=-1,  # already overdue, so the follow-up sweep picks it up
        outbound=(
            "Hi Daniel — a move-out clean for a 2-bedroom in Ikoyi comes to NGN 28,500 including "
            "the second bedroom. Happy to hold a slot if you'd like to go ahead."
        ),
    )
    return threads


def seed_tasks(db, business: Business, customers: dict) -> None:
    db.add(
        Task(
            business_id=business.id,
            title="Restock deep-clean supplies before Saturday",
            description="Two deep cleans booked this week; degreaser is low.",
            priority=TaskPriority.NORMAL,
            due_at=datetime.now(UTC) + timedelta(days=2),
            created_by="owner",
        )
    )
    db.flush()


def main() -> None:
    with session_scope() as db:
        business = upsert_business(db)
        wipe(db, business.id)
        business = upsert_business(db)

        services = seed_services(db, business)
        seed_policies(db, business)
        customers = seed_customers(db, business)
        complaint_booking = seed_history(db, business, customers, services)
        threads = seed_conversations(db, business, customers, complaint_booking)
        seed_tasks(db, business, customers)

        log.info("business      %s  %s", business.id, business.name)
        log.info("services      %d", len(services))
        log.info("customers     %d", len(customers))
        log.info("")
        log.info("Demo entry points:")
        log.info("  booking request   conversation %s  (Amaka Eze)", threads["booking"].id)
        log.info(
            "  complaint         conversation %s  (Sarah Johnson, booking %s @ NGN %s)",
            threads["complaint"].id,
            complaint_booking.reference,
            f"{float(complaint_booking.price):,.0f}",
        )
        log.info(
            "  stale quote       conversation %s  (Daniel Okoro, follow-up overdue)",
            threads["quote"].id,
        )


if __name__ == "__main__":
    main()
