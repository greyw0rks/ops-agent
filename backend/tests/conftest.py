"""Test fixtures.

Each test runs inside a transaction on a real Postgres connection which is rolled
back afterwards, so tests exercise the actual SQL and constraints without leaving
anything behind.
"""

import pytest
from sqlalchemy.orm import Session

from app.db.models import Base, Business, BusinessPolicy, Customer, Service
from app.db.session import engine
from app.services.business import DEFAULT_POLICIES


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def business(db: Session) -> Business:
    """A business open weekdays 09:00–17:00, two jobs at a time, in UTC.

    UTC keeps the arithmetic in the tests obvious; timezone handling is exercised
    separately.
    """
    row = Business(
        name="Test Cleaners Ltd",
        industry="home services",
        timezone="UTC",
        currency="NGN",
        opening_hours={
            "mon": ["09:00", "17:00"],
            "tue": ["09:00", "17:00"],
            "wed": ["09:00", "17:00"],
            "thu": ["09:00", "17:00"],
            "fri": ["09:00", "17:00"],
        },
        concurrent_capacity=2,
        slot_interval_minutes=60,
    )
    db.add(row)
    db.flush()
    for policy_type, rules in DEFAULT_POLICIES.items():
        db.add(BusinessPolicy(business_id=row.id, policy_type=policy_type, rules=dict(rules)))
    db.flush()
    return row


@pytest.fixture
def service(db: Session, business: Business) -> Service:
    row = Service(
        business_id=business.id,
        name="Standard Home Cleaning",
        base_price=7500,
        duration_minutes=120,
        price_modifiers={"bedrooms": 1500},
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def customer(db: Session, business: Business) -> Customer:
    row = Customer(
        business_id=business.id,
        name="Ada Nwosu",
        email="ada@example.com",
        phone="+2348030001111",
        preferences={},
    )
    db.add(row)
    db.flush()
    return row
