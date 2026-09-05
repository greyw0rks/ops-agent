"""Approvals — the human half of the loop.

Deciding an approval does two things: it records the decision, and it resumes the
run that was waiting on it. The resume happens in the background because it puts
the agent back to work, which takes as long as any other run.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.runner import resume
from app.api.deps import current_business, require_owner
from app.db.enums import ApprovalStatus
from app.db.models import Business
from app.db.session import get_db
from app.services import approvals as approval_service
from app.services import runs as run_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approvals", tags=["approvals"], dependencies=[Depends(require_owner)])


class DecisionIn(BaseModel):
    approved: bool
    note: str | None = None
    decided_by: str = "owner"


@router.get("")
def list_approvals(
    status: str | None = ApprovalStatus.PENDING,
    business: Business = Depends(current_business),
    db: Session = Depends(get_db),
) -> dict:
    """The owner's decision queue."""
    rows = approval_service.list_approvals(db, business.id, status=status)
    return {"count": len(rows), "approvals": rows}


@router.get("/{approval_id}")
def get_approval(
    approval_id: str,
    business: Business = Depends(current_business),
    db: Session = Depends(get_db),
) -> dict:
    approval = approval_service.get_approval(db, business.id, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="unknown approval")
    payload = approval_service.approval_dict(approval, business.timezone)
    payload["run"] = run_service.get_run(db, business.id, approval.run_id)
    return payload


@router.post("/{approval_id}/decide")
def decide(
    approval_id: str,
    decision: DecisionIn,
    background: BackgroundTasks,
    wait: bool = False,
    business: Business = Depends(current_business),
    db: Session = Depends(get_db),
) -> dict:
    """Approve or reject, then put the agent back to work."""
    outcome = approval_service.resolve_approval(
        db,
        business.id,
        approval_id,
        approved=decision.approved,
        decided_by=decision.decided_by,
        note=decision.note,
    )
    if not outcome["ok"]:
        code = 409 if outcome.get("error") == "already_decided" else 404
        raise HTTPException(status_code=code, detail=outcome)

    run_id = outcome["approval"]["run_id"]
    # The resumed agent reads this decision from its own connection, so it has to be
    # committed before the run restarts — otherwise the gate sees a still-pending
    # approval and the run blocks on the row this request is holding.
    db.commit()

    if wait:
        result = resume(run_id)
        return {
            "approval": outcome["approval"],
            "run_id": result.run_id,
            "status": result.status,
            "summary": result.summary,
            "actions": result.actions,
            "pending_approvals": result.pending_approvals,
            "error": result.error,
        }

    background.add_task(resume, run_id)
    return {"approval": outcome["approval"], "run_id": run_id, "status": "resuming"}
