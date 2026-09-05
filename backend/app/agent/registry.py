"""The tool registry.

One list, grouped by domain, so what the agent can reach is obvious at a glance
and adding a capability is a one-line change in a reviewable place.
"""

from app.tools import approvals, billing, bookings, business, communications, customers, operations

CUSTOMER_TOOLS = [
    customers.find_customer,
    customers.get_customer_history,
    customers.create_customer,
    customers.update_customer,
]

BOOKING_TOOLS = [
    bookings.check_availability,
    bookings.get_booking,
    bookings.create_booking,
    bookings.reschedule_booking,
    bookings.cancel_booking,
]

BUSINESS_TOOLS = [
    business.get_service_catalog,
    business.find_service,
    business.get_business_policy,
    business.calculate_price,
]

COMMUNICATION_TOOLS = [
    communications.get_conversation,
    communications.send_message,
    communications.resolve_conversation,
]

OPERATIONS_TOOLS = [
    operations.create_task,
    operations.get_open_tasks,
    operations.update_task,
    operations.complete_task,
]

BILLING_TOOLS = [
    billing.issue_refund,
    billing.apply_discount,
    billing.record_supplier_invoice,
]

APPROVAL_TOOLS = [
    approvals.request_approval,
    approvals.get_approval_status,
]

ALL_TOOLS = [
    *CUSTOMER_TOOLS,
    *BOOKING_TOOLS,
    *BUSINESS_TOOLS,
    *COMMUNICATION_TOOLS,
    *OPERATIONS_TOOLS,
    *BILLING_TOOLS,
    *APPROVAL_TOOLS,
]

TOOL_GROUPS = {
    "customer": CUSTOMER_TOOLS,
    "booking": BOOKING_TOOLS,
    "business": BUSINESS_TOOLS,
    "communication": COMMUNICATION_TOOLS,
    "operations": OPERATIONS_TOOLS,
    "billing": BILLING_TOOLS,
    "approval": APPROVAL_TOOLS,
}


def tool_names() -> list[str]:
    return [t.tool_name for t in ALL_TOOLS]
