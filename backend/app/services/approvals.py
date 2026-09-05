"""Approvals — the decisions the agent hands back to a human.

An approval row is bound to a Strands interrupt id. Resolving it does not "tell
the agent what happened"; it resumes the exact paused tool call, so the approved
action is the one the owner looked at.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ApprovalStatus, RiskLevel
from app.db.models import Approval
from app.services.business import get_business
from app.services.common import local_iso, money


def create_approval(
    db: Session,
    business_id: str,
    run_id: str,
    interrupt_id: str,
    action_type: str,
    title: str,
    reason: str,
    recommended_action: str,
    payload: dict,
    evidence: list | None = None,
    policy_basis: str | None = None,
    amount: float | None = None,
    risk_level: str = RiskLevel.HIGH,
) -> Approval:
    business = get_business(db, business_id)
    approval = Approval(
        business_id=business_id,
        run_id=run_id,
        interrupt_id=interrupt_id,
        action_type=action_type,
        risk_level=risk_level,
        title=title,
        reason=reason,
        recommended_action=recommended_action,
        policy_basis=policy_basis,
        amount=money(amount) if amount is not None else None,
        currency=business.currency if amount is not None else None,
        evidence=evidence or [],
        payload=payload,
        status=ApprovalStatus.PENDING,
    )
    db.add(approval)
    db.flush()
    return approval


def approval_dict(approval: Approval, tz: str) -> dict:
    return {
        "approval_id": approval.id,
        "run_id": approval.run_id,
        "action_type": approval.action_type,
        "risk_level": approval.risk_level,
        "title": approval.title,
        "reason": approval.reason,
        "recommended_action": approval.recommended_action,
        "policy_basis": approval.policy_basis,
        "amount": money(approval.amount) if approval.amount is not None else None,
        "currency": approval.currency,
        "evidence": approval.evidence or [],
        "payload": approval.payload or {},
        "status": approval.status,
        "decided_by": approval.decided_by,
        "decided_at": local_iso(approval.decided_at, tz),
        "decision_note": approval.decision_note,
        "requested_at": local_iso(approval.created_at, tz),
    }


def get_approval(db: Session, business_id: str, approval_id: str) -> Approval | None:
    approval = db.get(Approval, approval_id)
    if approval is None or approval.business_id != business_id:
        return None
    return approval


def find_by_interrupt(db: Session, run_id: str, interrupt_id: str) -> Approval | None:
    return db.scalars(
        select(Approval).where(Approval.run_id == run_id, Approval.interrupt_id == interrupt_id)
    ).first()


def find_latest_by_action(db: Session, run_id: str, action_type: str) -> Approval | None:
    """Most recent decision raised for a given action type on this run."""
    return db.scalars(
        select(Approval)
        .where(Approval.run_id == run_id, Approval.action_type == action_type)
        .order_by(Approval.created_at.desc())
    ).first()


def list_approvals(
    db: Session, business_id: str, status: str | None = ApprovalStatus.PENDING, limit: int = 50
) -> list[dict]:
    stmt = select(Approval).where(Approval.business_id == business_id)
    if status:
        stmt = stmt.where(Approval.status == status)
    rows = db.scalars(stmt.order_by(Approval.created_at.desc()).limit(limit)).all()
    tz = get_business(db, business_id).timezone
    return [approval_dict(r, tz) for r in rows]


def pending_approvals(db: Session, business_id: str) -> list[Approval]:
    return list(
        db.scalars(
            select(Approval).where(
                Approval.business_id == business_id, Approval.status == ApprovalStatus.PENDING
            )
        ).all()
    )


def resolve_approval(
    db: Session,
    business_id: str,
    approval_id: str,
    approved: bool,
    decided_by: str = "owner",
    note: str | None = None,
) -> dict:
    """Mark an approval decided. The caller then resumes the paused run."""
    approval = get_approval(db, business_id, approval_id)
    if approval is None:
        return {"ok": False, "error": f"unknown approval_id {approval_id!r}"}
    if approval.status != ApprovalStatus.PENDING:
        return {
            "ok": False,
            "error": "already_decided",
            "status": approval.status,
            "decided_by": approval.decided_by,
        }

    approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    approval.decided_by = decided_by
    approval.decided_at = datetime.now(UTC)
    approval.decision_note = note
    db.flush()

    tz = get_business(db, business_id).timezone
    return {"ok": True, "approval": approval_dict(approval, tz)}
