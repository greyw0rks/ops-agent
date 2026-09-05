"""Business context assembly.

The agent is given a compact, factual snapshot of the business it works for —
today's date in the right timezone, what is on sale, what the operating limits are,
and what is already outstanding. Anything larger than this is fetched with a tool
rather than pushed into the prompt, so context stays small and current.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ApprovalStatus, TaskStatus
from app.db.models import Approval, Business, Service, Task
from app.services.business import get_all_policies
from app.services.common import money, to_local


def business_snapshot(db: Session, business: Business) -> dict:
    """Facts the agent should not have to spend a tool call to learn."""
    now_local = to_local(datetime.now(UTC), business.timezone)

    services = db.scalars(
        select(Service).where(Service.business_id == business.id, Service.active.is_(True))
    ).all()

    open_tasks = db.scalar(
        select(Task.id).where(Task.business_id == business.id, Task.status == TaskStatus.OPEN).limit(1)
    )
    open_task_count = len(
        db.scalars(
            select(Task.id).where(Task.business_id == business.id, Task.status == TaskStatus.OPEN)
        ).all()
    )
    pending_approvals = len(
        db.scalars(
            select(Approval.id).where(
                Approval.business_id == business.id, Approval.status == ApprovalStatus.PENDING
            )
        ).all()
    )

    return {
        "business_id": business.id,
        "name": business.name,
        "industry": business.industry,
        "currency": business.currency,
        "timezone": business.timezone,
        "today": now_local.strftime("%Y-%m-%d"),
        "weekday": now_local.strftime("%A"),
        "local_time": now_local.strftime("%H:%M"),
        "opening_hours": business.opening_hours or {},
        "concurrent_capacity": business.concurrent_capacity,
        "services": [
            {
                "service_id": s.id,
                "name": s.name,
                "price": money(s.base_price),
                "duration_minutes": s.duration_minutes,
            }
            for s in services
        ],
        "policies": get_all_policies(db, business.id),
        "open_tasks": open_task_count,
        "has_open_tasks": bool(open_tasks),
        "pending_approvals": pending_approvals,
    }


def render_snapshot(snapshot: dict) -> str:
    """Format the snapshot as the block that goes into the system prompt."""
    lines = [
        f"Business: {snapshot['name']} ({snapshot['industry']})",
        f"Currency: {snapshot['currency']}    Timezone: {snapshot['timezone']}",
        f"Right now: {snapshot['weekday']} {snapshot['today']} at {snapshot['local_time']} local time.",
        f"Capacity: {snapshot['concurrent_capacity']} jobs can run at the same time.",
        "",
        "Opening hours:",
    ]
    hours = snapshot["opening_hours"] or {}
    if hours:
        for day, window in hours.items():
            lines.append(f"  {day}: {window[0]}–{window[1]}")
        closed = [d for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun") if d not in hours]
        if closed:
            lines.append(f"  closed: {', '.join(closed)}")
    else:
        lines.append("  not configured")

    lines += ["", "Services:"]
    for s in snapshot["services"]:
        lines.append(
            f"  {s['service_id']}  {s['name']} — {snapshot['currency']} {s['price']:,.2f}"
            f" ({s['duration_minutes']} min)"
        )

    lines += ["", "Operating limits the owner has set:"]
    policies = snapshot["policies"]
    refund = policies.get("refund", {})
    discount = policies.get("discount", {})
    cancellation = policies.get("cancellation", {})
    rescheduling = policies.get("rescheduling", {})
    currency = snapshot["currency"]
    if refund:
        lines.append(
            f"  Refunds: yours to make below {currency} {float(refund.get('auto_approve_below', 0)):,.2f};"
            f" the owner decides up to {currency} {float(refund.get('approval_required_below', 0)):,.2f};"
            f" above that it is theirs alone."
            f" Refund window: {refund.get('window_days', 'n/a')} days after the job."
        )
    if discount:
        lines.append(
            f"  Discounts: yours up to {float(discount.get('auto_approve_percent', 0)):g}%;"
            f" the owner decides up to {float(discount.get('approval_required_percent', 0)):g}%."
        )
    if cancellation:
        lines.append(
            f"  Cancellations: free with {cancellation.get('free_cancellation_hours', 0)}h notice,"
            f" otherwise a {float(cancellation.get('late_cancellation_fee_percent', 0)):g}% fee applies."
        )
    if rescheduling:
        lines.append(
            f"  Rescheduling: {rescheduling.get('free_reschedules', 0)} moves without asking,"
            f" minimum {rescheduling.get('min_notice_hours', 0)}h notice."
        )

    if snapshot["open_tasks"] or snapshot["pending_approvals"]:
        lines += [
            "",
            f"Outstanding: {snapshot['open_tasks']} open task(s),"
            f" {snapshot['pending_approvals']} decision(s) waiting on the owner.",
        ]

    return "\n".join(lines)
