"""Core business entities: the business itself, what it sells, who it sells to,
and the rules it operates under.
"""

from datetime import time

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.ids import id_factory


class Business(Base, TimestampMixin):
    __tablename__ = "businesses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("business"))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    industry: Mapped[str] = mapped_column(String(80), default="services")
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Lagos")
    currency: Mapped[str] = mapped_column(String(8), default="NGN")
    contact_email: Mapped[str | None] = mapped_column(String(160))
    contact_phone: Mapped[str | None] = mapped_column(String(40))

    # Working hours, as {"mon": ["08:00", "18:00"], ...}. Days absent are closed.
    opening_hours: Mapped[dict] = mapped_column(JSON, default=dict)
    # How many jobs the business can run at the same time.
    concurrent_capacity: Mapped[int] = mapped_column(Integer, default=2)
    slot_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)

    services: Mapped[list["Service"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    customers: Mapped[list["Customer"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    policies: Mapped[list["BusinessPolicy"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )


class Service(Base, TimestampMixin):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("service"))
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    base_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=120)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Free-form modifiers the pricing service understands, e.g. {"bedrooms": 1500}.
    price_modifiers: Mapped[dict] = mapped_column(JSON, default=dict)

    business: Mapped[Business] = relationship(back_populates="services")


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("business_id", "email", name="uq_customers_business_email"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("customer"))
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(160), index=True)
    phone: Mapped[str | None] = mapped_column(String(40), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    # Stable preferences the agent should respect, e.g. {"preferred_period": "afternoon"}.
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    lifetime_value: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    business: Mapped[Business] = relationship(back_populates="customers")


class BusinessPolicy(Base, TimestampMixin):
    """A configurable operating rule.

    This is the security boundary for consequential actions: the risk engine
    reads these rows, the language model does not get to reinterpret them.
    """

    __tablename__ = "business_policies"
    __table_args__ = (UniqueConstraint("business_id", "policy_type", name="uq_business_policies_type"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=id_factory("business_policy"))
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True, nullable=False)
    policy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    rules: Mapped[dict] = mapped_column(JSON, default=dict)
    # Prose the agent may quote back to a customer.
    summary: Mapped[str | None] = mapped_column(Text)

    business: Mapped[Business] = relationship(back_populates="policies")


DEFAULT_OPENING_HOURS = {
    "mon": ["08:00", "18:00"],
    "tue": ["08:00", "18:00"],
    "wed": ["08:00", "18:00"],
    "thu": ["08:00", "18:00"],
    "fri": ["08:00", "18:00"],
    "sat": ["09:00", "16:00"],
}


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))
