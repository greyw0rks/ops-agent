"""Internal tasks — the work the agent hands to a human rather than doing itself."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import TaskPriority, TaskStatus
from app.db.models import Task
from app.services.business import get_business
from app.services.common import local_iso


def _task_dict(task: Task, tz: str) -> dict:
    return {
        "task_id": task.id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "status": task.status,
        "due_at": local_iso(task.due_at, tz),
        "booking_id": task.booking_id,
        "customer_id": task.customer_id,
        "created_by": task.created_by,
    }


def create_task(
    db: Session,
    business_id: str,
    title: str,
    description: str | None = None,
    priority: str = TaskPriority.NORMAL,
    due_in_hours: float | None = None,
    booking_id: str | None = None,
    customer_id: str | None = None,
    created_by: str = "agent",
) -> dict:
    if priority not in set(TaskPriority):
        priority = TaskPriority.NORMAL
    due_at = datetime.now(UTC) + timedelta(hours=due_in_hours) if due_in_hours else None
    task = Task(
        business_id=business_id,
        title=title,
        description=description,
        priority=priority,
        due_at=due_at,
        booking_id=booking_id,
        customer_id=customer_id,
        created_by=created_by,
    )
    db.add(task)
    db.flush()
    tz = get_business(db, business_id).timezone
    return {"ok": True, "created": True, **_task_dict(task, tz)}


def update_task(db: Session, business_id: str, task_id: str, fields: dict) -> dict:
    task = db.get(Task, task_id)
    if task is None or task.business_id != business_id:
        return {"ok": False, "error": f"unknown task_id {task_id!r}"}

    allowed = {"title", "description", "priority", "status", "due_at"}
    for key, value in fields.items():
        if key in allowed:
            setattr(task, key, value)
    db.flush()
    tz = get_business(db, business_id).timezone
    return {"ok": True, "updated": sorted(set(fields) & allowed), **_task_dict(task, tz)}


def complete_task(db: Session, business_id: str, task_id: str) -> dict:
    task = db.get(Task, task_id)
    if task is None or task.business_id != business_id:
        return {"ok": False, "error": f"unknown task_id {task_id!r}"}
    task.status = TaskStatus.DONE
    db.flush()
    tz = get_business(db, business_id).timezone
    return {"ok": True, "completed": True, **_task_dict(task, tz)}


def get_open_tasks(db: Session, business_id: str, limit: int = 50) -> dict:
    tz = get_business(db, business_id).timezone
    tasks = db.scalars(
        select(Task)
        .where(
            Task.business_id == business_id,
            Task.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS)),
        )
        .order_by(Task.due_at.asc().nullslast(), Task.created_at.desc())
        .limit(limit)
    ).all()
    now = datetime.now(UTC)
    return {
        "ok": True,
        "count": len(tasks),
        "overdue": sum(1 for t in tasks if t.due_at and t.due_at < now),
        "tasks": [_task_dict(t, tz) for t in tasks],
    }


def due_tasks(db: Session, business_id: str, now: datetime | None = None) -> list[Task]:
    now = now or datetime.now(UTC)
    return list(
        db.scalars(
            select(Task).where(
                Task.business_id == business_id,
                Task.status == TaskStatus.OPEN,
                Task.due_at.isnot(None),
                Task.due_at <= now,
            )
        ).all()
    )
