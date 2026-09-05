"""Shared helpers for the service layer."""

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo


def money(value: Decimal | float | int | None) -> float:
    """Normalise a monetary value to two decimal places as a float.

    Tool results are serialised into the model's context, so they must be plain
    JSON types — `Decimal` is not.
    """
    if value is None:
        return 0.0
    quantised = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(quantised)


def to_utc(value: datetime, tz: str) -> datetime:
    """Interpret a naive datetime as business-local time and convert to UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(tz))
    return value.astimezone(UTC)


def to_local(value: datetime, tz: str) -> datetime:
    """Render a stored UTC datetime in the business's own timezone."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo(tz))


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def local_iso(value: datetime | None, tz: str) -> str | None:
    """Business-local ISO string — what a human in the demo expects to read."""
    return to_local(value, tz).isoformat() if value else None


PERIODS: dict[str, tuple[int, int]] = {
    "morning": (8, 12),
    "afternoon": (12, 17),
    "evening": (17, 20),
    "any": (0, 24),
}


def period_window(period: str | None) -> tuple[int, int]:
    """Map a fuzzy period word onto an hour range."""
    if not period:
        return PERIODS["any"]
    return PERIODS.get(period.strip().lower(), PERIODS["any"])


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def round_up_to_interval(value: datetime, minutes: int) -> datetime:
    """Round a time forward onto the next slot boundary."""
    remainder = (value.minute % minutes, value.second, value.microsecond)
    if remainder == (0, 0, 0):
        return value
    bump = minutes - (value.minute % minutes)
    return (value + timedelta(minutes=bump)).replace(second=0, microsecond=0)
