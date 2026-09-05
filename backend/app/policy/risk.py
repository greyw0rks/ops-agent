"""Static risk classification for every tool the agent can call.

Risk lives here, in the application, not in the system prompt. The prompt tells
the model what the tools are for; this table and the policy engine decide what it
is allowed to do with them. A jailbreak in the conversation cannot edit this file.
"""

from app.db.enums import RiskLevel

TOOL_RISK: dict[str, RiskLevel] = {
    # --- read-only ---
    "find_customer": RiskLevel.LOW,
    "get_customer_history": RiskLevel.LOW,
    "get_service_catalog": RiskLevel.LOW,
    "find_service": RiskLevel.LOW,
    "get_business_policy": RiskLevel.LOW,
    "calculate_price": RiskLevel.LOW,
    "check_availability": RiskLevel.LOW,
    "get_booking": RiskLevel.LOW,
    "get_conversation": RiskLevel.LOW,
    "get_open_tasks": RiskLevel.LOW,
    "get_approval_status": RiskLevel.LOW,
    # --- routine writes the owner delegated outright ---
    "create_customer": RiskLevel.LOW,
    "update_customer": RiskLevel.LOW,
    "create_booking": RiskLevel.LOW,
    "reschedule_booking": RiskLevel.LOW,
    "create_task": RiskLevel.LOW,
    "update_task": RiskLevel.LOW,
    "complete_task": RiskLevel.LOW,
    "record_supplier_invoice": RiskLevel.LOW,
    "resolve_conversation": RiskLevel.LOW,
    # --- outward-facing or partly reversible ---
    "send_message": RiskLevel.MEDIUM,
    "cancel_booking": RiskLevel.MEDIUM,
    "apply_discount": RiskLevel.MEDIUM,
    # --- moves money out ---
    "issue_refund": RiskLevel.HIGH,
    # --- escalation itself is always permitted ---
    "request_approval": RiskLevel.LOW,
}

#: Tools whose effect leaves the system: money, calendar, or the customer's inbox.
CONSEQUENTIAL_TOOLS = frozenset(
    {
        "issue_refund",
        "apply_discount",
        "cancel_booking",
        "send_message",
        "create_booking",
        "reschedule_booking",
    }
)

#: Tools that must be re-checked against the business policy on every call,
#: even when the model has called them before in the same run.
ALWAYS_RE_EVALUATE = frozenset({"issue_refund", "apply_discount", "cancel_booking"})


def risk_of(tool_name: str) -> RiskLevel:
    """Unknown tools are treated as high risk rather than waved through."""
    return TOOL_RISK.get(tool_name, RiskLevel.HIGH)
