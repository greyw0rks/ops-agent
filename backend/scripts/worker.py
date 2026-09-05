"""The background worker.

This is the part that makes the agent something other than reactive. In AWS the same
job is an EventBridge schedule hitting the API; locally it is this process.

    python -m scripts.worker                 # every 15 minutes
    python -m scripts.worker --interval 60   # every minute, for a demo
"""

import argparse
import logging
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler

from app.agent.runner import handle_event
from app.db.enums import EventType
from app.db.session import session_scope
from app.services import business as business_service
from app.services import conversations as conversation_service
from app.services import tasks as task_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("worker")


def sweep_follow_ups() -> None:
    """Chase threads the agent promised to come back to."""
    with session_scope() as db:
        business = business_service.get_default_business(db)
        targets = [(c.id, c.customer_id) for c in conversation_service.due_follow_ups(db, business.id)]
        business_id = business.id

    if not targets:
        log.info("follow-ups: nothing due")
        return

    log.info("follow-ups: %d thread(s) due", len(targets))
    for conversation_id, customer_id in targets:
        result = handle_event(
            EventType.FOLLOW_UP_DUE,
            business_id=business_id,
            trigger_ref=conversation_id,
            payload={"conversation_id": conversation_id, "customer_id": customer_id},
        )
        log.info("follow-up run=%s status=%s", result.run_id, result.status)


def sweep_due_tasks() -> None:
    """Look at internal tasks that have come due."""
    with session_scope() as db:
        business = business_service.get_default_business(db)
        targets = [t.id for t in task_service.due_tasks(db, business.id)]
        business_id = business.id

    if not targets:
        log.info("tasks: nothing due")
        return

    log.info("tasks: %d due", len(targets))
    for task_id in targets:
        result = handle_event(
            EventType.TASK_DUE,
            business_id=business_id,
            trigger_ref=task_id,
            payload={"task_id": task_id},
        )
        log.info("task run=%s status=%s", result.run_id, result.status)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=900, help="seconds between sweeps")
    parser.add_argument("--once", action="store_true", help="run one sweep and exit")
    args = parser.parse_args()

    if args.once:
        sweep_follow_ups()
        sweep_due_tasks()
        return

    scheduler = BlockingScheduler()
    scheduler.add_job(sweep_follow_ups, "interval", seconds=args.interval, id="follow-ups")
    # Offset so the two sweeps do not start a run at the same instant.
    scheduler.add_job(sweep_due_tasks, "interval", seconds=args.interval, id="due-tasks", jitter=30)

    def shutdown(*_):
        log.info("worker stopping")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("worker started — sweeping every %ds", args.interval)
    scheduler.start()


if __name__ == "__main__":
    main()
