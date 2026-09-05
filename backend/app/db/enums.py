"""Domain enumerations.

Stored as plain strings in Postgres. Using `str` enums keeps them ergonomic in
Python and JSON-serialisable in tool results without a custom encoder, while
avoiding native Postgres enum types (which are painful to migrate).
"""

from enum import StrEnum


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class BookingStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class ConversationStatus(StrEnum):
    OPEN = "open"
    AWAITING_CUSTOMER = "awaiting_customer"
    AWAITING_BUSINESS = "awaiting_business"
    RESOLVED = "resolved"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageAuthor(StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"
    OWNER = "owner"


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class RunStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class ActionStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"


class PolicyDecision(StrEnum):
    """What the application decided to do with a proposed tool call."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class RefundStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    REJECTED = "rejected"


class InvoiceStatus(StrEnum):
    RECEIVED = "received"
    SCHEDULED = "scheduled"
    PAID = "paid"
    DISPUTED = "disputed"


class EventType(StrEnum):
    """Events that can wake the agent."""

    CUSTOMER_MESSAGE_RECEIVED = "CustomerMessageReceived"
    DOCUMENT_RECEIVED = "DocumentReceived"
    FOLLOW_UP_DUE = "FollowUpDue"
    TASK_DUE = "TaskDue"
    APPROVAL_RESOLVED = "ApprovalResolved"
    DAILY_SUMMARY_DUE = "DailySummaryDue"
