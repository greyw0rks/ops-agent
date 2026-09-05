# Architecture

## The one decision everything else follows from

An agent that can spend money needs two different kinds of thinking, and only one of
them belongs to a language model.

*What should happen here?* is a judgement call about a customer, a service that went
wrong, and a business relationship. A model is good at that.

*Is the agent allowed to do that?* is a question about authority. It has a correct
answer, that answer is in a database row the owner controls, and a model must not be
the thing that answers it — because anything a model reads, including a customer's
message, can influence what it decides.

So the two are separate layers, and the second one runs first:

```
model proposes  →  application rules  →  human decides (if needed)  →  service executes
```

## Layers

```
┌────────────────────────────────────────────────────────────────────┐
│  Events                                                            │
│  CustomerMessageReceived · FollowUpDue · DocumentReceived ·         │
│  TaskDue · DailySummaryDue                                         │
└─────────────────────────────┬──────────────────────────────────────┘
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  app/agent/runner.py — run lifecycle                               │
│  opens an AgentRun, loads business context, binds the run context,  │
│  invokes the agent, records how it ended                            │
└─────────────────────────────┬──────────────────────────────────────┘
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  Strands Agent                                                     │
│  system prompt = role + business snapshot + authority + playbooks   │
│  tools = app/agent/registry.py                                      │
└─────────────────────────────┬──────────────────────────────────────┘
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  app/policy/gate.py — PolicyGate (InterventionHandler)             │
│  before_tool_call → Proceed | Deny | Confirm                        │
└─────────────────────────────┬──────────────────────────────────────┘
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  app/tools/*.py — 25 @tool functions                               │
│  no business logic, no SQL; read run context, call a service        │
└─────────────────────────────┬──────────────────────────────────────┘
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  app/services/*.py — the only code that touches Postgres           │
│  availability, pricing, booking writes, refunds, audit records      │
└────────────────────────────────────────────────────────────────────┘
```

Nothing skips a layer. In particular the agent has no database handle, so "the model
wrote a row we didn't expect" is not a failure mode that exists.

## Where the limits live

`business_policies` rows, one per policy type, owned by the business:

```json
{
  "refund":       {"auto_approve_below": 5000, "approval_required_below": 60000,
                   "manual_review_above": 60000, "window_days": 14},
  "discount":     {"auto_approve_percent": 10, "approval_required_percent": 25},
  "cancellation": {"free_cancellation_hours": 24, "late_cancellation_fee_percent": 30},
  "rescheduling": {"free_reschedules": 2, "min_notice_hours": 4}
}
```

`PUT /api/business/policies/{type}` changes them. The next tool call is gated against
the new numbers — no redeploy, no prompt editing. That is the product's real control
surface: the owner is not configuring an AI, they are setting the limits they would
give a new member of staff.

`app/policy/engine.py` turns a proposed call into a `Ruling`:

| Ruling | What happens | Example |
|---|---|---|
| `ALLOW` | tool runs, action logged | NGN 2,500 refund |
| `REQUIRE_APPROVAL` | run pauses, approval written | NGN 7,500 refund |
| `DENY` | tool refused, reason returned to the model | NGN 90,000 refund |

A tool with no rule falls back to its entry in `app/policy/risk.py`. A tool in
neither is treated as HIGH risk and denied — so a capability added without a declared
risk fails closed. A test asserts the registry and the risk table agree, because the
failure is otherwise silent.

## Pause and resume

This is the mechanically interesting part, so here it is in full.

```
1. Model emits  issue_refund(booking_id="BH-1041", amount=7500)

2. PolicyGate.before_tool_call
     ├─ evaluate() → REQUIRE_APPROVAL
     ├─ compute the interrupt id Strands is about to generate
     │     v1:before_tool_call:{toolUseId}:{uuid5(NAMESPACE_OID, "policy-gate")}
     ├─ write the Approval row against that id           ← committed now
     ├─ write an AgentAction row: awaiting_approval
     └─ return Confirm(prompt=...)

3. Strands raises the interrupt, persists the run through the SessionManager,
   and returns  stop_reason == "interrupt"

4. runner._pause() marks the run awaiting_approval and returns the pending
   approvals. The HTTP request is over. The process can exit.

        ... minutes or hours pass ...

5. POST /api/approvals/{id}/decide  {"approved": true, "note": "..."}
     ├─ approval → APPROVED, decided_by, decided_at, note
     ├─ commit          ← the resumed agent reads this on another connection
     └─ runner.resume(run_id)

6. resume() rebuilds the Agent with the same session_id. The SessionManager
   restores the messages and the interrupt state. Then:

        agent([{"interruptResponse": {"interruptId": ..., "response": "yes"}}])

7. The gate is consulted again, the framework finds the stored response,
   evaluate() accepts it, and issue_refund actually runs — stamped with the
   approval id that authorised it.
```

Two details worth calling out.

**The interrupt id is predicted, not discovered.** Strands builds it from the tool-use
id and a uuid5 of the handler name, both of which the gate knows. So the approval row
can be written before the pause, and the owner's queue is never behind the agent's
state. `tests/test_gate.py` pins this against the SDK's own `_interrupt_id`, so a
future release that changes the format breaks a test rather than orphaning approvals.

**A rejection carries the reason, not just the verdict.** Strands cancels a refused
tool with `CONFIRMATION_FAILED: <prompt>`. The gate's `after_tool_call` intercepts
that and appends the owner's note to the tool result, so the agent sees *"the owner
rejected this. Their reason: half was fair, offer a re-clean instead"*. The difference
in behaviour is large: without it the agent knows only that it was blocked, and tends
to go quiet on the customer.

## Transaction boundaries

The agent's tools each open a short transaction and commit immediately. That is
deliberate — an audit trail should be durable as it happens, and holding one
transaction open across several seconds of model latency is a good way to serialise a
whole application behind a language model.

The consequence is a rule for API handlers: **commit before invoking the agent.** A
request that inserts an inbound message and then calls the agent synchronously in the
same transaction will deadlock — the agent reads on a different connection, cannot see
the uncommitted row, and blocks on the lock the request is still holding while the
request waits for the agent. The `db.commit()` calls in `app/api/routes/events.py` and
`approvals.py` are load-bearing, and they are commented as such.

`next_sequence()` locks the run row with `SELECT ... FOR UPDATE` before numbering an
action, because Strands executes a turn's tool calls concurrently and `max() + 1`
across separate transactions will hand the same number to two of them.

## Defence in depth

The gate is the enforcement point, but it is not the only check, because a single
enforcement point is a single point of failure for money.

1. **Prompt** — tells the agent the limits exist and are not its to negotiate. Weakest
   layer; treated as guidance, not control.
2. **Risk table** — every tool has a declared level; unknown tools are HIGH and denied.
3. **Policy engine** — the owner's numbers, applied to the actual arguments.
4. **The gate** — refuses or pauses before the tool function is entered.
5. **Service layer** — `issue_refund` and `apply_discount` raise `PolicyViolation` if
   asked to exceed the ceiling without an approval id, independently of the gate. This
   is what a test of "the gate was bypassed" asserts against.
6. **Per-run caps** — one refund per run, so a retry loop cannot pay twice.
7. **Idempotent messaging** — an identical outbound body inside five minutes is
   suppressed, so a model that loses track of a completed call cannot double-message a
   customer.

Layers 5–7 exist because layers 1–4 are code, and code has bugs.

## Data model

```
Business ──┬── Service
           ├── Customer ──┬── Booking ──── Refund
           │              └── Conversation ──── Message
           ├── BusinessPolicy        ← the security boundary
           ├── Task
           ├── SupplierInvoice
           └── AgentRun ──┬── AgentAction     ← what the agent did
                          └── Approval        ← what it asked about
```

`AgentRun.session_id` is the handle Strands resumes by. `Approval.interrupt_id` binds
a decision to the exact paused tool call. Those two columns are what make the human in
the loop a real participant rather than a notification.

## AWS

| Concern | Local | AWS |
|---|---|---|
| Model | Anthropic-compatible endpoint | Bedrock (`BedrockModel`) |
| Paused run state | `FileSessionManager` | `S3SessionManager` |
| Scheduling | `POST /api/sweeps/follow-ups` | EventBridge → the same endpoint |
| Database | Postgres in Docker | RDS Postgres |
| Documents | local path | S3 |
| Traces | stdout | CloudWatch via Strands telemetry |

Every one of those is a configuration change, not a code change, which was the point
of putting the provider behind `app/agent/model.py` and the session behind
`build_session_manager()`.
