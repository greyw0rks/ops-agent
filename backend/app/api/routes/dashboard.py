"""Read models for the dashboard: runs, business config, and the operational lists."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.model import describe_model
from app.api.deps import current_business, require_owner
from app.db.enums import ApprovalStatus, RunStatus
from app.db.models import Business, BusinessPolicy, Conversation
from app.db.session import get_db
from app.services import approvals as approval_service
from app.services import billing as billing_service
from app.services import bookings as booking_service
from app.services import business as business_service
from app.services import conversations as conversation_service
from app.services import customers as customer_service
from app.services import runs as run_service
from app.services import tasks as task_service
from app.services.common import local_iso, money

router = APIRouter(prefix="/api", tags=["dashboard"], dependencies=[Depends(require_owner)])


@router.get("/business")
def get_business_config(
    business: Business = Depends(current_business), db: Session = Depends(get_db)
) -> dict:
    """Everything the owner can configure, plus how the agent is wired up."""
    return {
        "business_id": business.id,
        "name": business.name,
        "industry": business.industry,
        "currency": business.currency,
        "timezone": business.timezone,
        "contact_email": business.contact_email,
        "contact_phone": business.contact_phone,
        "opening_hours": business.opening_hours or {},
        "concurrent_capacity": business.concurrent_capacity,
        "slot_interval_minutes": business.slot_interval_minutes,
        "catalog": business_service.get_service_catalog(db, business.id)["services"],
        "policies": {
            policy_type: business_service.get_policy(db, business.id, policy_type)
            for policy_type in ("refund", "discount", "cancellation", "rescheduling")
        },
        "agent": describe_model(),
    }


class PolicyIn(BaseModel):
    rules: dict
    summary: str | None = None


@router.put("/business/policies/{policy_type}")
def update_policy(
    policy_type: str,
    body: PolicyIn,
    business: Business = Depends(current_business),
    db: Session = Depends(get_db),
) -> dict:
    """Change an operating limit.

    This is the real control surface of the product: the owner moves a number here
    and the agent's authority changes on the next tool call, with no redeploy and no
    prompt editing.
    """
    if policy_type not in business_service.DEFAULT_POLICIES:
        raise HTTPException(status_code=400, detail=f"unknown policy type {policy_type!r}")

    row = db.scalars(
        select(BusinessPolicy).where(
            BusinessPolicy.business_id == business.id,
            BusinessPolicy.policy_type == policy_type,
        )
    ).first()
    if row is None:
        row = BusinessPolicy(business_id=business.id, policy_type=policy_type)
        db.add(row)

    allowed = set(business_service.DEFAULT_POLICIES[policy_type])
    rejected = sorted(set(body.rules) - allowed)
    row.rules = {k: v for k, v in body.rules.items() if k in allowed}
    if body.summary is not None:
        row.summary = body.summary
    db.flush()

    return {"ok": True, "policy_type": policy_type, "rules": row.rules, "rejected": rejected}


@router.get("/runs")
def list_runs(
    limit: int = 30,
    status: str | None = None,
    business: Business = Depends(current_business),
    db: Session = Depends(get_db),
) -> dict:
    """The activity feed."""
    runs = run_service.list_runs(db, business.id, limit=limit, status=status)
    return {"count": len(runs), "runs": runs}


@router.get("/runs/{run_id}")
def get_run(
    run_id: str, business: Business = Depends(current_business), db: Session = Depends(get_db)
) -> dict:
    run = run_service.get_run(db, business.id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown run")
    return run


@router.get("/customers")
def list_customers(
    business: Business = Depends(current_business), db: Session = Depends(get_db)
) -> dict:
    from app.db.models import Customer

    rows = db.scalars(
        select(Customer).where(Customer.business_id == business.id).order_by(Customer.name)
    ).all()
    return {
        "count": len(rows),
        "customers": [
            {
                "customer_id": c.id,
                "name": c.name,
                "email": c.email,
                "phone": c.phone,
                "address": c.address,
                "lifetime_value": money(c.lifetime_value),
                "preferences": c.preferences or {},
            }
            for c in rows
        ],
    }


@router.get("/customers/{customer_id}")
def get_customer(
    customer_id: str, business: Business = Depends(current_business), db: Session = Depends(get_db)
) -> dict:
    history = customer_service.get_customer_history(db, business.id, customer_id, limit=25)
    if not history.get("ok"):
        raise HTTPException(status_code=404, detail=history.get("error"))
    return history


@router.get("/bookings")
def list_bookings(
    upcoming: bool = True,
    limit: int = 50,
    business: Business = Depends(current_business),
    db: Session = Depends(get_db),
) -> dict:
    rows = booking_service.list_bookings(db, business.id, upcoming_only=upcoming, limit=limit)
    return {"count": len(rows), "bookings": rows}


@router.get("/conversations")
def list_conversations(
    limit: int = 30, business: Business = Depends(current_business), db: Session = Depends(get_db)
) -> dict:
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.business_id == business.id)
        .order_by(Conversation.last_message_at.desc().nullslast())
        .limit(limit)
    ).all()
    return {
        "count": len(rows),
        "conversations": [
            {
                "conversation_id": c.id,
                "customer_id": c.customer_id,
                "subject": c.subject,
                "channel": c.channel,
                "status": c.status,
                "last_message_at": local_iso(c.last_message_at, business.timezone),
                "follow_up_due_at": local_iso(c.follow_up_due_at, business.timezone),
                "message_count": len(c.messages),
            }
            for c in rows
        ],
    }


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    business: Business = Depends(current_business),
    db: Session = Depends(get_db),
) -> dict:
    thread = conversation_service.get_conversation(db, business.id, conversation_id, limit=100)
    if not thread.get("ok"):
        raise HTTPException(status_code=404, detail=thread.get("error"))
    return thread


@router.get("/tasks")
def list_tasks(
    business: Business = Depends(current_business), db: Session = Depends(get_db)
) -> dict:
    return task_service.get_open_tasks(db, business.id)


@router.get("/dashboard")
def dashboard(
    business: Business = Depends(current_business), db: Session = Depends(get_db)
) -> dict:
    """One call for the whole home screen.

    Ordered the way the owner reads it: what needs me, what the agent has been
    doing, what is coming up.
    """
    pending = approval_service.list_approvals(db, business.id, status=ApprovalStatus.PENDING)
    runs = run_service.list_runs(db, business.id, limit=12)
    upcoming = booking_service.list_bookings(db, business.id, upcoming_only=True, limit=8)
    tasks = task_service.get_open_tasks(db, business.id, limit=10)
    refunds = billing_service.list_refunds(db, business.id, limit=10)

    completed = [r for r in runs if r["status"] == RunStatus.COMPLETED]
    autonomous = [r for r in completed if not any(a["approval_id"] for a in r.get("actions", []))]
    actions_taken = sum(r["action_count"] for r in runs)

    return {
        "business": {
            "name": business.name,
            "currency": business.currency,
            "timezone": business.timezone,
        },
        "needs_you": pending,
        "activity": runs,
        "upcoming_bookings": upcoming,
        "open_tasks": tasks["tasks"],
        "recent_refunds": refunds,
        "stats": {
            "runs": len(runs),
            "completed": len(completed),
            "handled_without_you": len(autonomous),
            "awaiting_you": len(pending),
            "tool_calls": actions_taken,
            "bookings_upcoming": len(upcoming),
            "open_tasks": tasks["count"],
            "overdue_tasks": tasks["overdue"],
        },
    }
