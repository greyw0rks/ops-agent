"""Drive the agent from the command line.

The dashboard has a button for each of these; this script is the same code path
without a browser, which makes it the fastest way to watch a run.

    python -m scripts.simulate_event booking
    python -m scripts.simulate_event complaint
    python -m scripts.simulate_event message --conversation conv_x --text "..."
    python -m scripts.simulate_event followups
    python -m scripts.simulate_event approve --approval apr_x
    python -m scripts.simulate_event reject  --approval apr_x --note "..."
"""

import argparse
import logging
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.agent.runner import RunResult, handle_event, resume
from app.db.enums import ApprovalStatus, ConversationStatus, EventType, MessageDirection
from app.db.models import Conversation, Message
from app.db.session import session_scope
from app.services import approvals as approval_service
from app.services import business as business_service
from app.services import conversations as conversation_service

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
logging.getLogger("app").setLevel(logging.INFO)
log = logging.getLogger("simulate")

GREY, BOLD, RESET = "\033[90m", "\033[1m", "\033[0m"
GREEN, YELLOW, RED = "\033[32m", "\033[33m", "\033[31m"

STATUS_MARK = {
    "success": f"{GREEN}✓{RESET}",
    "error": f"{RED}✗{RESET}",
    "blocked": f"{RED}⊘{RESET}",
    "awaiting_approval": f"{YELLOW}⏸{RESET}",
}


def _pick_conversation(db, business_id: str, needle: str) -> Conversation | None:
    """Find a seeded thread by a word in its subject."""
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.business_id == business_id)
        .order_by(Conversation.last_message_at.desc().nullslast())
    ).all()
    for row in rows:
        if needle.lower() in (row.subject or "").lower():
            return row
    return None


def _inject(db, conversation: Conversation, text: str) -> None:
    db.add(
        Message(
            conversation_id=conversation.id,
            direction=MessageDirection.INBOUND,
            author="customer",
            body=text,
            sent_at=datetime.now(UTC),
        )
    )
    conversation.last_message_at = datetime.now(UTC)
    conversation.status = ConversationStatus.AWAITING_BUSINESS
    db.flush()


def report(result: RunResult) -> None:
    """Print the run the way the dashboard's activity feed shows it."""
    print()
    print(f"{BOLD}run {result.run_id}{RESET}  {result.status}")
    print(f"{GREY}{'─' * 72}{RESET}")

    for action in result.actions:
        mark = STATUS_MARK.get(action["status"], "·")
        risk = action["risk_level"]
        risk_tag = f"{GREY}[{risk}]{RESET}" if risk == "LOW" else f"{YELLOW}[{risk}]{RESET}"
        print(f"  {mark} {action['tool']:<26} {risk_tag}")
        if action["policy_decision"] != "allow":
            print(f"      {YELLOW}policy: {action['policy_decision']}{RESET} — {action['policy_reason']}")

    if result.pending_approvals:
        for approval in result.pending_approvals:
            print()
            print(f"{YELLOW}{BOLD}  DECISION REQUIRED{RESET}  {approval['approval_id']}")
            print(f"  {approval['title']}")
            print(f"  Recommended: {approval['recommended_action']}")
            print(f"  Why: {approval['reason']}")
            if approval["policy_basis"]:
                print(f"  {GREY}Policy: {approval['policy_basis']}{RESET}")
            for item in approval["evidence"]:
                print(f"  {GREY}· {item['label']} ({item['id']}){RESET}")
            print(f"\n  Approve with: python -m scripts.simulate_event approve "
                  f"--approval {approval['approval_id']}")

    if result.summary:
        print()
        print(f"{BOLD}  Summary{RESET}")
        for line in result.summary.splitlines():
            print(f"  {line}")

    if result.error:
        print(f"\n  {RED}error: {result.error}{RESET}")
    print()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_conversation(needle: str, text: str | None) -> RunResult:
    """Fire a customer-message event on a seeded thread."""
    with session_scope() as db:
        business = business_service.get_default_business(db)
        conversation = _pick_conversation(db, business.id, needle)
        if conversation is None:
            sys.exit(f"no conversation matching {needle!r} — run `python -m scripts.seed` first")
        if text:
            _inject(db, conversation, text)
        business_id, conversation_id = business.id, conversation.id
        customer_id = conversation.customer_id

    return handle_event(
        EventType.CUSTOMER_MESSAGE_RECEIVED,
        business_id=business_id,
        trigger_ref=conversation_id,
        payload={"conversation_id": conversation_id, "customer_id": customer_id},
    )


def cmd_followups() -> list[RunResult]:
    """Run the follow-up sweep — the agent working with nobody watching."""
    with session_scope() as db:
        business = business_service.get_default_business(db)
        due = conversation_service.due_follow_ups(db, business.id)
        targets = [(business.id, c.id, c.customer_id) for c in due]

    if not targets:
        print("nothing due")
        return []

    results = []
    for business_id, conversation_id, customer_id in targets:
        results.append(
            handle_event(
                EventType.FOLLOW_UP_DUE,
                business_id=business_id,
                trigger_ref=conversation_id,
                payload={"conversation_id": conversation_id, "customer_id": customer_id},
            )
        )
    return results


def cmd_decide(approval_id: str | None, approved: bool, note: str | None) -> RunResult:
    """Resolve a decision and resume the run that was waiting on it."""
    with session_scope() as db:
        business = business_service.get_default_business(db)
        if approval_id is None:
            pending = approval_service.pending_approvals(db, business.id)
            if not pending:
                sys.exit("no pending approvals")
            approval_id = pending[0].id
            print(f"using pending approval {approval_id}")
        outcome = approval_service.resolve_approval(
            db, business.id, approval_id, approved=approved, decided_by="owner", note=note
        )
        if not outcome["ok"]:
            sys.exit(f"could not resolve: {outcome['error']}")
        run_id = outcome["approval"]["run_id"]
        verdict = outcome["approval"]["status"]

    print(f"{BOLD}{verdict.upper()}{RESET} by owner — resuming run {run_id}")
    return resume(run_id)


def cmd_pending() -> None:
    with session_scope() as db:
        business = business_service.get_default_business(db)
        rows = approval_service.list_approvals(db, business.id, status=ApprovalStatus.PENDING)
    if not rows:
        print("no pending approvals")
        return
    for row in rows:
        print(f"{row['approval_id']}  {row['title']}")
        print(f"  {row['recommended_action']}")
        print(f"  {GREY}{row['reason']}{RESET}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["booking", "complaint", "quote", "message", "followups", "approve", "reject", "pending"],
    )
    parser.add_argument("--conversation", help="subject keyword or conversation id")
    parser.add_argument("--text", help="the customer message to inject")
    parser.add_argument("--approval", help="approval id (defaults to the oldest pending)")
    parser.add_argument("--note", help="note to record with the decision")
    args = parser.parse_args()

    if args.command == "pending":
        cmd_pending()
        return

    if args.command == "followups":
        for result in cmd_followups():
            report(result)
        return

    if args.command in ("approve", "reject"):
        report(cmd_decide(args.approval, args.command == "approve", args.note))
        return

    needle = {"booking": "Cleaning", "complaint": "deep clean", "quote": "Quote"}.get(
        args.command, args.conversation or ""
    )
    if args.command == "message" and not needle:
        sys.exit("message needs --conversation")
    report(cmd_conversation(needle, args.text))


if __name__ == "__main__":
    main()
