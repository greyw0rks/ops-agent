"""Operations tools: internal tasks for the humans."""

from strands import tool

from app.db.session import session_scope
from app.services import tasks as service
from app.tools._context import current


@tool
def create_task(
    title: str,
    description: str | None = None,
    priority: str = "normal",
    due_in_hours: float | None = None,
    booking_id: str | None = None,
    customer_id: str | None = None,
) -> dict:
    """Put work on the owner's list.

    Use this for anything that needs a human: a job the crew has to prepare for, a
    supplier query, or a decision that falls outside what you are allowed to make.
    Write the title as an instruction the owner can act on without re-reading the
    whole thread.

    Args:
        title: What needs doing, e.g. "Call Sarah about Saturday access code".
        description: The context behind it.
        priority: `low`, `normal`, `high` or `urgent`.
        due_in_hours: When it should be done by, in hours from now.
        booking_id: The booking it relates to, if any.
        customer_id: The customer it relates to, if any.

    Returns:
        The created task.
    """
    ctx = current()
    with session_scope() as db:
        return service.create_task(
            db,
            ctx.business_id,
            title=title,
            description=description,
            priority=priority,
            due_in_hours=due_in_hours,
            booking_id=booking_id,
            customer_id=customer_id,
        )


@tool
def get_open_tasks() -> dict:
    """List the outstanding internal tasks.

    Useful before creating a new one, so you do not duplicate work that is already
    on the list.

    Returns:
        Open tasks, soonest due first, and how many are overdue.
    """
    ctx = current()
    with session_scope() as db:
        return service.get_open_tasks(db, ctx.business_id)


@tool
def update_task(task_id: str, fields: dict) -> dict:
    """Change a task's title, description, priority or status.

    Args:
        task_id: The task to change.
        fields: Any of `title`, `description`, `priority`, `status`.

    Returns:
        The updated task.
    """
    ctx = current()
    with session_scope() as db:
        return service.update_task(db, ctx.business_id, task_id, fields)


@tool
def complete_task(task_id: str) -> dict:
    """Mark a task done.

    Close a task once the underlying work is actually finished — not when you have
    merely noted it. If it turned out to need a person, leave it open and say what
    is blocking it instead.

    Args:
        task_id: The task to close.

    Returns:
        The closed task.
    """
    ctx = current()
    with session_scope() as db:
        return service.complete_task(db, ctx.business_id, task_id)
