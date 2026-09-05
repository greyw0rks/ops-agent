"""Operational entities: the work the business actually does and the paper trail
around it — bookings, conversations, internal tasks, refunds, supplier invoices.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.enums import (
    BookingStatus,
    ConversationStatus,
    InvoiceStatus,
    MessageAuthor,
    MessageDirection,
    RefundStatus,
    TaskPriority,
    TaskStatus,
)
from app.db.ids import id_factory


class Booking(Base, TimestampMixin):
    __tablename__ = "bookings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("booking"))
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True, nullable=False)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), index=True, nullable=False)
    # Short human reference used in customer-facing messages, e.g. "BH-1042".
    reference: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=BookingStatus.CONFIRMED)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    price_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    # "agent" or "owner" — makes autonomous work visible in the dashboard.
    created_by: Mapped[str] = mapped_column(String(24), default="agent")
    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    customer: Mapped["Customer"] = relationship()  # noqa: F821
    service: Mapped["Service"] = relationship()  # noqa: F821


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("conversation"))
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True, nullable=False)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), index=True)
    channel: Mapped[str] = mapped_column(String(24), default="email")
    subject: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default=ConversationStatus.OPEN)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Set when the agent is waiting on the customer; drives the follow-up sweep.
    follow_up_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    follow_up_count: Mapped[int] = mapped_column(Integer, default=0)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.sent_at"
    )
    customer: Mapped["Customer | None"] = relationship()  # noqa: F821


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("message"))
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True, nullable=False
    )
    direction: Mapped[str] = mapped_column(String(16), default=MessageDirection.INBOUND)
    author: Mapped[str] = mapped_column(String(16), default=MessageAuthor.CUSTOMER)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set when this message was produced inside an agent run.
    agent_run_id: Mapped[str | None] = mapped_column(String(32), index=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Task(Base, TimestampMixin):
    """Internal work for the humans — the agent creates these, it does not do them."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("task"))
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16), default=TaskPriority.NORMAL)
    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.OPEN, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    booking_id: Mapped[str | None] = mapped_column(ForeignKey("bookings.id"))
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"))
    created_by: Mapped[str] = mapped_column(String(24), default="agent")


class Refund(Base, TimestampMixin):
    __tablename__ = "refunds"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("refund"))
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True, nullable=False)
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id"), index=True, nullable=False)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=RefundStatus.PAID)
    # The approval that authorised this, when one was required.
    approval_id: Mapped[str | None] = mapped_column(String(32), index=True)
    agent_run_id: Mapped[str | None] = mapped_column(String(32), index=True)


class SupplierInvoice(Base, TimestampMixin):
    __tablename__ = "supplier_invoices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("supplier_invoice"))
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True, nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(160), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(64), index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default=InvoiceStatus.RECEIVED)
    # Where the source document lives (local path in dev, S3 key in AWS).
    document_key: Mapped[str | None] = mapped_column(String(400))
    extracted: Mapped[dict] = mapped_column(JSON, default=dict)
    agent_run_id: Mapped[str | None] = mapped_column(String(32), index=True)
