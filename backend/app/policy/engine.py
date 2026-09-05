"""The policy engine.

One entry point — `evaluate()` — answers a single question: given this proposed
tool call, on this business, in this run, is the agent allowed to proceed on its
own, does it need a human, or is it out of bounds entirely?

The answer is derived from `business_policies` rows the owner controls. The model
never sees this code path; it only sees the outcome.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ActionStatus, ApprovalStatus, PolicyDecision, RiskLevel
from app.db.models import AgentAction, Approval, Booking
from app.policy.risk import risk_of
from app.services.billing import refunded_total
from app.services.bookings import get_booking
from app.services.business import get_business, get_policy
from app.services.common import money


@dataclass
class Ruling:
    """The application's verdict on one proposed tool call."""

    decision: PolicyDecision
    risk_level: RiskLevel
    reason: str
    policy_basis: str | None = None
    # Populated when the ruling is REQUIRE_APPROVAL, to build the owner's card.
    title: str | None = None
    recommended_action: str | None = None
    amount: float | None = None
    evidence: list = field(default_factory=list)
    # Overrides the tool name as the approval's action type. Used by
    # `request_approval`, where the meaningful label is in the arguments.
    action_type: str | None = None

    @property
    def requires_approval(self) -> bool:
        return self.decision == PolicyDecision.REQUIRE_APPROVAL

    @property
    def denied(self) -> bool:
        return self.decision == PolicyDecision.DENY


def _allow(risk: RiskLevel, reason: str, basis: str | None = None) -> Ruling:
    return Ruling(decision=PolicyDecision.ALLOW, risk_level=risk, reason=reason, policy_basis=basis)


def evaluate(
    db: Session,
    business_id: str,
    run_id: str,
    tool_name: str,
    tool_input: dict,
) -> Ruling:
    """Rule on a proposed tool call."""
    risk = risk_of(tool_name)

    handler = _HANDLERS.get(tool_name)
    if handler is None:
        if risk == RiskLevel.HIGH:
            return Ruling(
                decision=PolicyDecision.DENY,
                risk_level=risk,
                reason=f"{tool_name} is not a recognised tool and is treated as high risk.",
                policy_basis="unknown tool default-deny",
            )
        return _allow(risk, f"{tool_name} is a routine {risk.lower()}-risk action.")

    return handler(db, business_id, run_id, tool_name, tool_input, risk)


# ---------------------------------------------------------------------------
# Per-tool rules
# ---------------------------------------------------------------------------


def _rule_refund(
    db: Session, business_id: str, run_id: str, tool_name: str, args: dict, risk: RiskLevel
) -> Ruling:
    rules = get_policy(db, business_id, "refund")["rules"]
    auto_below = float(rules.get("auto_approve_below", 0) or 0)
    approval_below = float(rules.get("approval_required_below", 0) or 0)
    window_days = int(rules.get("window_days", 0) or 0)

    business = get_business(db, business_id)
    amount = money(args.get("amount") or 0)
    booking_ref = args.get("booking_id") or ""
    booking = get_booking(db, business_id, booking_ref) if booking_ref else None

    if booking is None:
        return Ruling(
            decision=PolicyDecision.DENY,
            risk_level=risk,
            reason=f"No booking matches {booking_ref!r}, so there is nothing to refund.",
            policy_basis="refund must reference a real booking",
        )

    # One refund per run. A retry loop must not be able to pay twice.
    already_this_run = db.scalars(
        select(AgentAction).where(
            AgentAction.run_id == run_id,
            AgentAction.tool == "issue_refund",
            AgentAction.status == ActionStatus.SUCCESS,
        )
    ).first()
    if already_this_run:
        return Ruling(
            decision=PolicyDecision.DENY,
            risk_level=risk,
            reason="A refund has already been issued in this run. A second one needs a new request.",
            policy_basis="one refund per agent run",
        )

    paid = money(booking.price)
    already = refunded_total(db, booking.id)
    if amount + already > paid:
        return Ruling(
            decision=PolicyDecision.DENY,
            risk_level=risk,
            reason=(
                f"{business.currency} {amount:,.2f} would take total refunds past the "
                f"{business.currency} {paid:,.2f} paid on {booking.reference}."
            ),
            policy_basis="refund cannot exceed the amount paid",
        )

    if window_days and booking.ends_at:
        age_days = (datetime.now(UTC) - booking.ends_at).days
        if age_days > window_days:
            return Ruling(
                decision=PolicyDecision.DENY,
                risk_level=risk,
                reason=(
                    f"{booking.reference} finished {age_days} days ago, outside the "
                    f"{window_days}-day refund window."
                ),
                policy_basis=f"refund window: {window_days} days",
            )

    evidence = _refund_evidence(db, booking)
    title = f"Refund {business.currency} {amount:,.2f} — {booking.reference}"
    recommended = f"Refund {business.currency} {amount:,.2f} against booking {booking.reference}."

    if auto_below and amount < auto_below:
        return _allow(
            risk,
            f"{business.currency} {amount:,.2f} is under the "
            f"{business.currency} {auto_below:,.2f} the owner pre-authorised.",
            basis=f"refund auto-approve below {auto_below}",
        )

    if approval_below and amount > approval_below:
        return Ruling(
            decision=PolicyDecision.DENY,
            risk_level=risk,
            reason=(
                f"{business.currency} {amount:,.2f} is above the "
                f"{business.currency} {approval_below:,.2f} ceiling the owner delegated. "
                "Open a task for the owner to handle this personally instead."
            ),
            policy_basis=f"refunds above {approval_below} are manual review only",
        )

    return Ruling(
        decision=PolicyDecision.REQUIRE_APPROVAL,
        risk_level=risk,
        reason=(
            f"{business.currency} {amount:,.2f} is above the "
            f"{business.currency} {auto_below:,.2f} auto-approval limit, so it needs the owner."
        ),
        policy_basis=f"refund approval band: {auto_below}–{approval_below}",
        title=title,
        recommended_action=recommended,
        amount=amount,
        evidence=evidence,
    )


def _refund_evidence(db: Session, booking: Booking) -> list:
    from app.db.models import Conversation

    evidence = [
        {"type": "booking", "id": booking.id, "label": f"Booking {booking.reference}"},
        {"type": "customer", "id": booking.customer_id, "label": "Customer record"},
    ]
    conversation = db.scalars(
        select(Conversation)
        .where(Conversation.customer_id == booking.customer_id)
        .order_by(Conversation.last_message_at.desc().nullslast())
    ).first()
    if conversation:
        evidence.append(
            {"type": "conversation", "id": conversation.id, "label": "Customer conversation"}
        )
    return evidence


def _rule_discount(
    db: Session, business_id: str, run_id: str, tool_name: str, args: dict, risk: RiskLevel
) -> Ruling:
    rules = get_policy(db, business_id, "discount")["rules"]
    auto_percent = float(rules.get("auto_approve_percent", 0) or 0)
    approval_percent = float(rules.get("approval_required_percent", 0) or 0)

    business = get_business(db, business_id)
    percent = float(args.get("percent") or 0)
    booking = get_booking(db, business_id, args.get("booking_id") or "")

    if booking is None:
        return Ruling(
            decision=PolicyDecision.DENY,
            risk_level=risk,
            reason="A discount needs an existing booking to apply to.",
            policy_basis="discount must reference a real booking",
        )

    amount = money(float(booking.price) * percent / 100)

    if auto_percent and percent <= auto_percent:
        return _allow(
            risk,
            f"{percent:g}% is within the {auto_percent:g}% the owner pre-authorised.",
            basis=f"discount auto-approve up to {auto_percent}%",
        )

    if approval_percent and percent > approval_percent:
        return Ruling(
            decision=PolicyDecision.DENY,
            risk_level=risk,
            reason=(
                f"{percent:g}% is beyond the {approval_percent:g}% ceiling the owner delegated. "
                "Open a task for the owner instead."
            ),
            policy_basis=f"discounts above {approval_percent}% are manual review only",
        )

    return Ruling(
        decision=PolicyDecision.REQUIRE_APPROVAL,
        risk_level=risk,
        reason=f"{percent:g}% is above the {auto_percent:g}% auto-approval limit.",
        policy_basis=f"discount approval band: {auto_percent}%–{approval_percent}%",
        title=f"{percent:g}% discount — {booking.reference}",
        recommended_action=(
            f"Apply a {percent:g}% discount to {booking.reference}, "
            f"reducing it by {business.currency} {amount:,.2f}."
        ),
        amount=amount,
        evidence=_refund_evidence(db, booking),
    )


def _rule_cancel(
    db: Session, business_id: str, run_id: str, tool_name: str, args: dict, risk: RiskLevel
) -> Ruling:
    """Cancelling is routine with notice; inside the free window it costs the customer money."""
    rules = get_policy(db, business_id, "cancellation")["rules"]
    free_hours = int(rules.get("free_cancellation_hours", 0) or 0)
    fee_percent = float(rules.get("late_cancellation_fee_percent", 0) or 0)

    business = get_business(db, business_id)
    booking = get_booking(db, business_id, args.get("booking_id") or "")
    if booking is None:
        return Ruling(
            decision=PolicyDecision.DENY,
            risk_level=risk,
            reason="No booking matches that reference.",
            policy_basis="cancellation must reference a real booking",
        )

    hours_notice = (booking.starts_at - datetime.now(UTC)).total_seconds() / 3600
    if hours_notice >= free_hours or fee_percent == 0:
        return _allow(
            risk,
            f"{hours_notice:.0f}h notice meets the {free_hours}h free-cancellation window.",
            basis=f"free cancellation with {free_hours}h notice",
        )

    fee = money(float(booking.price) * fee_percent / 100)
    return Ruling(
        decision=PolicyDecision.REQUIRE_APPROVAL,
        risk_level=risk,
        reason=(
            f"Only {hours_notice:.0f}h notice, inside the {free_hours}h window, so a "
            f"{fee_percent:g}% fee ({business.currency} {fee:,.2f}) applies. "
            "Waiving or charging it is the owner's call."
        ),
        policy_basis=f"late cancellation fee: {fee_percent}% inside {free_hours}h",
        title=f"Late cancellation — {booking.reference}",
        recommended_action=(
            f"Cancel {booking.reference} with {hours_notice:.0f}h notice and "
            f"charge the {business.currency} {fee:,.2f} late fee."
        ),
        amount=fee,
        evidence=_refund_evidence(db, booking),
    )


def _rule_send_message(
    db: Session, business_id: str, run_id: str, tool_name: str, args: dict, risk: RiskLevel
) -> Ruling:
    """Do not write to the customer while a decision about them is still open."""
    pending = db.scalars(
        select(Approval).where(Approval.run_id == run_id, Approval.status == ApprovalStatus.PENDING)
    ).first()
    if pending:
        return Ruling(
            decision=PolicyDecision.DENY,
            risk_level=risk,
            reason=(
                f"Approval {pending.id} is still open on this run. Do not message the customer "
                "until the owner has decided — you will be resumed automatically."
            ),
            policy_basis="no outbound messages while a decision is pending",
        )
    return _allow(risk, "Replying to a customer is delegated to the agent.")


def _rule_reschedule(
    db: Session, business_id: str, run_id: str, tool_name: str, args: dict, risk: RiskLevel
) -> Ruling:
    """Rescheduling is delegated, but not indefinitely."""
    rules = get_policy(db, business_id, "rescheduling")["rules"]
    free_moves = int(rules.get("free_reschedules", 0) or 0)

    booking = get_booking(db, business_id, args.get("booking_id") or "")
    if booking is None:
        return Ruling(
            decision=PolicyDecision.DENY,
            risk_level=risk,
            reason="No booking matches that reference.",
            policy_basis="reschedule must reference a real booking",
        )

    moves = (booking.notes or "").count("Rescheduled:")
    if free_moves and moves >= free_moves:
        return Ruling(
            decision=PolicyDecision.REQUIRE_APPROVAL,
            risk_level=risk,
            reason=(
                f"{booking.reference} has already been moved {moves} times, at or past the "
                f"{free_moves} the owner allows without being asked."
            ),
            policy_basis=f"free reschedules: {free_moves}",
            title=f"Reschedule #{moves + 1} — {booking.reference}",
            recommended_action=(
                f"Move {booking.reference} to {args.get('day')} at {args.get('start_time')}."
            ),
            evidence=_refund_evidence(db, booking),
        )
    return _allow(risk, f"Move {moves + 1} of {free_moves or 'unlimited'} allowed without approval.")


def _rule_explicit_request(
    db: Session, business_id: str, run_id: str, tool_name: str, args: dict, risk: RiskLevel
) -> Ruling:
    """The agent asked for a human itself. Always honour that."""
    return Ruling(
        decision=PolicyDecision.REQUIRE_APPROVAL,
        risk_level=RiskLevel.MEDIUM,
        reason=str(args.get("reason") or "The agent asked for a human decision."),
        policy_basis="raised by the agent",
        title=str(args.get("title") or "Decision requested"),
        recommended_action=str(args.get("recommended_action") or "Proceed as described."),
        amount=float(args["amount"]) if args.get("amount") is not None else None,
        action_type=str(args.get("action_type") or "request_approval"),
    )


_HANDLERS = {
    "issue_refund": _rule_refund,
    "apply_discount": _rule_discount,
    "cancel_booking": _rule_cancel,
    "send_message": _rule_send_message,
    "reschedule_booking": _rule_reschedule,
    "request_approval": _rule_explicit_request,
}
