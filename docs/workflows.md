# Workflows

Five journeys. None of them is a hard-coded state machine — the agent chooses its own
tool sequence — but the prompt gives it a playbook per situation and the policy engine
constrains where each one can end up.

## A — New booking

**Trigger** `CustomerMessageReceived`

> "Hi, I'd like to book a standard cleaning for my 3-bedroom flat on Saturday
> afternoon if you have anything free."

```
get_conversation → find_customer → get_service_catalog
      → calculate_price → check_availability → create_booking
      → send_message → resolve_conversation
```

**Outcome** Booked, priced from the catalogue, confirmed with a reference. No human
involved.

The order matters and the prompt insists on it: price and availability come from tools
before anything is promised, and the booking is written with the same number that was
quoted.

## B — Reschedule

**Trigger** `CustomerMessageReceived`

> "Can we move my cleaning from tomorrow to Friday afternoon?"

```
get_conversation → find_customer → get_booking
      → check_availability(new day) → reschedule_booking → send_message
```

**Outcome** Moved, unless the rescheduling policy says otherwise. Inside the notice
window the tool refuses and the agent offers what is actually available. On a third
move it pauses for the owner.

## C — Complaint and refund

**Trigger** `CustomerMessageReceived`

> "I'm really disappointed with yesterday's deep clean. The oven wasn't touched.
> I'd like a refund."

```
get_conversation → get_booking → get_business_policy("refund")
      → get_customer_history
      → issue_refund  ⏸ PAUSED
```

The refund is sized by the agent from the situation. The policy engine then decides
what happens to that number:

| Amount | Outcome |
|---|---|
| under NGN 5,000 | goes through, logged |
| NGN 5,000 – 60,000 | pauses for the owner |
| over NGN 60,000 | refused; the agent opens a task instead |
| more than was paid | refused |
| outside the 14-day window | refused |
| a second refund in the same run | refused |

While the decision is open, `send_message` is denied. The agent cannot tell the
customer a refund is coming before one has been agreed — which is the single most
damaging thing a well-meaning agent can do here.

On approval the paused call resumes and the agent finishes: refund, reply, update the
customer record, resolve the thread. On rejection it receives the owner's reasoning and
offers something else.

## D — Supplier invoice

**Trigger** `DocumentReceived`

```
read the document → identify supplier, amount, reference, due date
      → record_supplier_invoice → create_task (if something is off)
```

**Outcome** Filed. An identical supplier-and-reference pair is refused as a duplicate,
which is the common failure mode when the same invoice is emailed twice. Anything
ambiguous becomes a task rather than a guess.

## E — Follow-up on a stale thread

**Trigger** `FollowUpDue`, from a schedule — EventBridge in AWS,
`POST /api/sweeps/follow-ups` locally.

```
get_conversation → decide whether anything is genuinely outstanding
      → send_message (one nudge)   or   resolve_conversation
```

**Outcome** One chase, then it lets go. The prompt is explicit about never chasing
twice for the same thing, and `follow_up_count` and `resolve_conversation` make that
enforceable rather than aspirational.

This is the journey that separates an operations agent from a chatbot: nobody was in
the room. A quote had gone unanswered for four days, a timer fired, and the work
happened.

## The event model

```
CustomerMessageReceived   an inbound message on any channel
FollowUpDue               a thread the agent promised to chase
TaskDue                   an internal task has come due
DocumentReceived          an invoice or similar arrived
DailySummaryDue           end-of-day roundup for the owner
ApprovalResolved          a human decided; the paused run continues
```

Each one is a row in `agent_runs` with its trigger and payload, so "why did the agent
do this?" is always answerable from the database.
