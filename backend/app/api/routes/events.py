"""Event ingestion — the front door for everything that wakes the agent.

An agent run takes tens of seconds, so by default the API accepts the event, starts
the run in the background and returns immediately. The dashboard polls `/api/runs`
to watch it work. Pass `wait=true` when you want the finished result in the
response, which is what the demo scripts do.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.runner import handle_event
from app.api.deps import current_business, require_owner
from app.db.enums import EventType
from app.db.models import Business, Conversation
from app.db.session import get_db
from app.services import conversations as conversation_service
from app.services import customers as customer_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["events"], dependencies=[Depends(require_owner)])


class EventIn(BaseModel):
    type: EventType
    trigger_ref: str | None = None
    payload: dict = Field(default_factory=dict)


class InboundMessageIn(BaseModel):
    """A customer message arriving on any channel."""

    body: str
    conversation_id: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    customer_name: str | None = None
    channel: str = "email"
    subject: str | None = None


def _dispatch(
    background: BackgroundTasks,
    wait: bool,
    trigger: str,
    business_id: str,
    trigger_ref: str | None,
    payload: dict,
) -> dict:
    """Hand the event to the agent, either now or in the background.

    Note for callers: the request's own transaction must already be committed. The
    agent opens its own short transactions per tool call, so anything this request
    is still holding — a new inbound message, an updated conversation row — is both
    invisible to the agent and a lock it will block on.
    """
    if wait:
        result = handle_event(
            trigger, business_id=business_id, trigger_ref=trigger_ref, payload=payload
        )
        return {
            "accepted": True,
            "run_id": result.run_id,
            "status": result.status,
            "summary": result.summary,
            "actions": result.actions,
            "pending_approvals": result.pending_approvals,
            "error": result.error,
        }

    background.add_task(
        handle_event, trigger, business_id=business_id, trigger_ref=trigger_ref, payload=payload
    )
    return {"accepted": True, "status": "running", "trigger": trigger, "trigger_ref": trigger_ref}


@router.post("/events", status_code=202)
def ingest_event(
    event: EventIn,
    background: BackgroundTasks,
    wait: bool = False,
    business: Business = Depends(current_business),
    db: Session = Depends(get_db),
) -> dict:
    """Wake the agent for an arbitrary event."""
    business_id = business.id
    db.commit()  # don't hold a transaction open across the run
    return _dispatch(
        background, wait, event.type, business_id, event.trigger_ref, dict(event.payload)
    )


@router.post("/messages", status_code=202)
def receive_message(
    inbound: InboundMessageIn,
    background: BackgroundTasks,
    wait: bool = False,
    business: Business = Depends(current_business),
    db: Session = Depends(get_db),
) -> dict:
    """Take in a customer message and hand it to the agent.

    This is the seam a real channel integration plugs into: an SES inbound rule, a
    WhatsApp webhook, or a web form all reduce to the same three things — who wrote,
    what they said, and which thread it belongs to.
    """
    if inbound.conversation_id:
        thread = db.get(Conversation, inbound.conversation_id)
        if thread is None or thread.business_id != business.id:
            raise HTTPException(status_code=404, detail="unknown conversation_id")
    else:
        match = customer_service.find_customer(
            db,
            business.id,
            name=inbound.customer_name,
            email=inbound.customer_email,
            phone=inbound.customer_phone,
        )
        thread = conversation_service.get_or_create_conversation(
            db,
            business.id,
            customer_id=match.get("customer_id"),
            channel=inbound.channel,
            subject=inbound.subject or inbound.body[:60],
        )

    conversation_service.append_message(db, thread, inbound.body)
    # Release this request's locks before the agent starts: it reads the thread from
    # its own connection, so an uncommitted message is one it cannot see and a row it
    # would wait on.
    db.commit()

    payload = {"conversation_id": thread.id, "customer_id": thread.customer_id}
    response = _dispatch(
        background,
        wait,
        EventType.CUSTOMER_MESSAGE_RECEIVED,
        business.id,
        thread.id,
        payload,
    )
    response["conversation_id"] = thread.id
    return response


@router.post("/sweeps/follow-ups", status_code=202)
def sweep_follow_ups(
    background: BackgroundTasks,
    wait: bool = False,
    business: Business = Depends(current_business),
    db: Session = Depends(get_db),
) -> dict:
    """Chase every thread whose follow-up has come due.

    This is the endpoint a schedule calls — EventBridge in AWS, the local worker in
    development. It is the part that makes the agent something other than reactive.
    """
    due = conversation_service.due_follow_ups(db, business.id)
    targets = [(c.id, c.customer_id) for c in due]
    db.commit()

    dispatched = []
    for conversation_id, customer_id in targets:
        dispatched.append(
            _dispatch(
                background,
                wait,
                EventType.FOLLOW_UP_DUE,
                business.id,
                conversation_id,
                {"conversation_id": conversation_id, "customer_id": customer_id},
            )
        )
    return {"due": len(targets), "runs": dispatched}
