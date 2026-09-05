"""Resuming a paused run must not double-write.

The SDK is explicit that an interrupt is *re-execution, not continuation*: on resume
the `before_tool_call` handler runs again from the top, and only the `interrupt()` call
returns early with the stored answer. Anything the handler did before returning
`Confirm` therefore happens twice unless it is guarded.

Our gate writes three things before it pauses — an approval, an action row, and the
run's status — so this is the exact bug the caveat describes. These tests drive the
handler twice with the same tool-use id, the way a real resume does, and assert the
second pass is a no-op.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from strands.interventions import Confirm, Deny, Proceed

from app.db.enums import ActionStatus, ApprovalStatus
from app.db.models import AgentAction, Approval, Booking
from app.policy.gate import PolicyGate, interrupt_id_for
from app.services import approvals as approval_service
from app.services import runs as run_service
from app.tools import _context as run_context
from app.tools._context import RunContext


@dataclass
class FakeToolCallEvent:
    """Stands in for `BeforeToolCallEvent`.

    The gate only reads `tool_use`, so a stub keeps the test honest about what the
    handler actually depends on.
    """

    tool_use: dict[str, Any]
    cancel_tool: bool | str = False
    result: dict[str, Any] = field(default_factory=dict)
    cancel_message: str | None = None


def event_for(tool: str, tool_use_id: str, **args) -> FakeToolCallEvent:
    return FakeToolCallEvent(tool_use={"name": tool, "toolUseId": tool_use_id, "input": args})


@pytest.fixture
def refundable(db, business, service, customer) -> Booking:
    starts = datetime.now(UTC) - timedelta(days=1)
    booking = Booking(
        business_id=business.id,
        customer_id=customer.id,
        service_id=service.id,
        reference="TC-4001",
        starts_at=starts,
        ends_at=starts + timedelta(hours=2),
        status="completed",
        price=15000,
    )
    db.add(booking)
    db.flush()
    return booking


@pytest.fixture
def ctx(db, business, monkeypatch):
    """A bound run context, as the runner would set up.

    The gate opens its own `session_scope()` because in production it runs on a
    different connection from whatever triggered the run. That is the property the API
    handlers have to commit around — and in a test it means the gate cannot see this
    transaction, so `session_scope` is pointed at the test session for the duration.
    """

    @contextmanager
    def test_scope():
        yield db
        db.flush()

    monkeypatch.setattr("app.policy.gate.session_scope", test_scope)

    run = run_service.start_run(db, business_id=business.id, trigger="test")
    context = RunContext(business_id=business.id, run_id=run.id, trigger="test")
    with run_context.bind(context):
        yield context


def count(db, model, **where) -> int:
    stmt = select(func.count()).select_from(model)
    for key, value in where.items():
        stmt = stmt.where(getattr(model, key) == value)
    return db.scalar(stmt) or 0


def test_escalation_writes_one_approval_and_one_action(db, business, ctx, refundable):
    gate = PolicyGate()
    action = gate.before_tool_call(
        event_for("issue_refund", "toolu_a", booking_id=refundable.id, amount=7500, reason="oven")
    )

    assert isinstance(action, Confirm)
    assert count(db, Approval, run_id=ctx.run_id) == 1
    assert count(db, AgentAction, run_id=ctx.run_id) == 1

    approval = db.scalars(select(Approval).where(Approval.run_id == ctx.run_id)).one()
    assert approval.interrupt_id == interrupt_id_for("toolu_a")
    assert approval.status == ApprovalStatus.PENDING


def test_second_pass_on_resume_writes_nothing_new(db, business, ctx, refundable):
    """The handler re-runs on resume. It must not create a second decision."""
    gate = PolicyGate()
    args = {"booking_id": refundable.id, "amount": 7500, "reason": "oven"}

    gate.before_tool_call(event_for("issue_refund", "toolu_a", **args))
    raised = db.scalars(select(Approval).where(Approval.run_id == ctx.run_id)).one()
    approval_service.resolve_approval(
        db, business.id, raised.id, approved=True, note="Agreed."
    )

    # ... the framework re-enters the handler with the same tool-use id ...
    again = gate.before_tool_call(event_for("issue_refund", "toolu_a", **args))

    assert isinstance(again, Confirm), "still a confirm, so the framework can match the answer"
    assert count(db, Approval, run_id=ctx.run_id) == 1, "a second approval would ask twice"
    assert count(db, AgentAction, run_id=ctx.run_id) == 1, "a second action would double-count"


def test_a_different_tool_call_gets_its_own_decision(db, business, ctx, refundable):
    """Two genuine escalations in one run are two decisions, not a deduplication bug."""
    gate = PolicyGate()
    gate.before_tool_call(
        event_for("issue_refund", "toolu_a", booking_id=refundable.id, amount=7500, reason="oven")
    )
    gate.before_tool_call(
        event_for("cancel_booking", "toolu_b", booking_id=refundable.id, reason="late")
    )
    assert count(db, Approval, run_id=ctx.run_id) == 2


def test_re_evaluation_on_resume_respects_a_policy_changed_meanwhile(
    db, business, ctx, refundable
):
    """Re-execution is a feature here: the owner can tighten a limit mid-pause.

    The gate re-reads the policy on the second pass, so a refund that was merely
    escalated becomes refused if the ceiling moved below it while it sat in the queue.
    """
    from app.db.models import BusinessPolicy

    gate = PolicyGate()
    args = {"booking_id": refundable.id, "amount": 7500, "reason": "oven"}
    assert isinstance(gate.before_tool_call(event_for("issue_refund", "toolu_a", **args)), Confirm)

    policy = db.scalars(
        select(BusinessPolicy).where(
            BusinessPolicy.business_id == business.id, BusinessPolicy.policy_type == "refund"
        )
    ).one()
    policy.rules = {**policy.rules, "approval_required_below": 5000}
    db.flush()

    again = gate.before_tool_call(event_for("issue_refund", "toolu_a", **args))
    assert isinstance(again, Deny)


def test_allowed_tool_writes_no_rows_from_the_gate(db, ctx):
    """The observer records successful calls; the gate must not also record them."""
    gate = PolicyGate()
    action = gate.before_tool_call(event_for("check_availability", "toolu_c", date="2026-09-12"))
    assert isinstance(action, Proceed)
    assert count(db, AgentAction, run_id=ctx.run_id) == 0


def test_denied_tool_is_recorded_once_as_blocked(db, ctx):
    gate = PolicyGate()
    action = gate.before_tool_call(event_for("issue_refund", "toolu_d", booking_id="nope", amount=1))
    assert isinstance(action, Deny)
    rows = db.scalars(select(AgentAction).where(AgentAction.run_id == ctx.run_id)).all()
    assert len(rows) == 1
    assert rows[0].status == ActionStatus.BLOCKED


def test_gate_is_inert_without_a_run_context(db, refundable):
    """Direct tool invocation in a test must not be gated against a run that isn't there."""
    gate = PolicyGate()
    assert isinstance(
        gate.before_tool_call(event_for("issue_refund", "toolu_e", booking_id=refundable.id)),
        Proceed,
    )
