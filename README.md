# Ops Agent

An autonomous operations agent for small service businesses, built with the
[Strands Agents SDK](https://strandsagents.com). It reads what comes in, does the
work, and only interrupts the owner when there is a real decision to make.

Built for the **Agents for Humans Hackathon** — Professional Agents track.

---

## The problem

A three-person cleaning company in Lagos takes bookings by WhatsApp and email. Every
one of them is the same five minutes of work: find the customer, check the calendar,
work out the price, write it down, reply. Then there are the reschedules, the quotes
nobody answered, the supplier invoices, and the occasional complaint.

None of it is hard. All of it has to happen. It happens in the evening, after the
actual work, and it is the reason the owner has not taken a day off since March.

The parts that genuinely need a human are a small fraction of the total — and they
are the parts that get the least attention, because they are buried in the rest.

## What this does

The agent runs on events, not on someone opening an app.

| It handles | On its own | Asks first |
|---|---|---|
| New booking requests | ✅ identify, price, schedule, confirm | |
| Reschedules and cancellations with notice | ✅ | |
| Small refunds inside the owner's limit | ✅ | |
| Refunds above that limit | | ⏸ owner decides, agent resumes |
| Late cancellations where a fee is at stake | | ⏸ waiving it is the owner's call |
| Discounts beyond the pre-authorised percentage | | ⏸ |
| Quotes nobody answered | ✅ one nudge, then it lets go | |
| Supplier invoices | ✅ files them, flags duplicates | |
| Anything above the owner's ceiling | | ❌ refused outright, task opened instead |

Every run is recorded: which event woke the agent, which tools it called, what the
policy engine decided about each one, and what the owner chose. `GET /api/dashboard`
returns the owner's whole home screen from that record — so what they read is work that
happened, not a transcript of a model talking about work.

## The idea the whole thing is built on

Three concerns, kept apart on purpose:

```
        ┌──────────────────────────────────────────┐
        │  STRANDS AGENT                           │
        │  "This deserves a NGN 7,500 refund."     │   ← reasoning
        └────────────────────┬─────────────────────┘
                             │
        ┌────────────────────▼─────────────────────┐
        │  POLICY ENGINE                           │
        │  "7,500 > the 5,000 you pre-authorised." │   ← authority
        └────────────────────┬─────────────────────┘
                             │
        ┌────────────────────▼─────────────────────┐
        │  OWNER                                   │
        │  "Approved — and offer her an oven clean."│  ← judgement
        └────────────────────┬─────────────────────┘
                             │
        ┌────────────────────▼─────────────────────┐
        │  SERVICE LAYER                            │
        │  issue_refund() → Postgres                │  ← execution
        └───────────────────────────────────────────┘
```

The model decides *what should happen*. The application decides *whether it is
allowed*. Those are different questions, and only one of them can be answered by a
language model.

So the limits live in `business_policies` rows the owner controls, they are read by
`app/policy/engine.py`, and they are enforced by a Strands `InterventionHandler`
that runs **before** the tool function is entered. Nothing in a customer's message
can move them, because nothing in a customer's message is consulted.

The prompt says as much, in as many words: *"those limits are enforced by the
application, not by you — call the tool that does the right thing."* An agent that
knows it will be stopped has no reason to negotiate with itself about a ceiling.

## Architecture

```
   Customer message        Scheduled sweep         Supplier document
   (email / WhatsApp)      (EventBridge / cron)    (S3 / inbox)
          │                       │                       │
          └───────────────────────┼───────────────────────┘
                                  ▼
                    ┌─────────────────────────────┐
                    │  FastAPI  /api/events       │
                    │  opens an AgentRun          │
                    └──────────────┬──────────────┘
                                   ▼
                    ┌─────────────────────────────┐
                    │  STRANDS AGENT              │
                    │  Bedrock (Claude Sonnet)    │
                    │  25 tools, 7 domains        │
                    └──────────────┬──────────────┘
                                   │ proposes a tool call
                    ┌──────────────▼──────────────┐
                    │  PolicyGate                 │
                    │  InterventionHandler        │
                    │  ├─ Proceed  → run it       │
                    │  ├─ Deny     → refuse it    │
                    │  └─ Confirm  → pause it     │
                    └───────┬─────────────┬───────┘
                            │             │
                     allowed│             │needs a human
                            ▼             ▼
              ┌──────────────────┐   ┌──────────────────────┐
              │  Tool            │   │  Approval written    │
              │  ↓ Service layer │   │  Run state persisted │
              │  ↓ Postgres      │   │  (SessionManager)    │
              └────────┬─────────┘   └──────────┬───────────┘
                       │                        │
                       │             ┌──────────▼───────────┐
                       │             │  Owner's queue       │
                       │             │  approve / reject    │
                       │             └──────────┬───────────┘
                       │                        │ resumes the
                       │                        │ exact tool call
                       │             ┌──────────▼───────────┐
                       │             │  Agent continues     │
                       │             └──────────┬───────────┘
                       └────────────┬───────────┘
                                    ▼
                    ┌─────────────────────────────┐
                    │  AgentRun + AgentAction     │
                    │  the audit trail            │
                    └─────────────────────────────┘
```

The agent never touches Postgres. Every path is
`agent → tool → service → database`, which means every consequential write has a
single chokepoint that can be tested, logged and gated.

Full detail, including the pause/resume mechanics and why each boundary is where it
is: [docs/architecture.md](docs/architecture.md).

## Quickstart

Requirements: Docker, Python 3.12+, and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/greyw0rks/ops-agent.git
cd ops-agent

cp .env.example .env      # then set the model provider, see below
make db-up                # Postgres on :5437
make install              # backend deps into backend/.venv
make init-db              # create the schema
make seed                 # BrightHome Services + customers + three live threads
make api                  # http://localhost:8010/docs

make web-install          # dashboard deps
make web                  # http://localhost:3010
```

### Model provider

Every variable is namespaced `OPS_` so an ambient `ANTHROPIC_API_KEY` or
`AWS_REGION` exported for some other tool cannot quietly take over the agent's
configuration. (It can, and it did, which is why the prefix exists.)

**Amazon Bedrock** — the intended runtime:

```bash
OPS_MODEL_PROVIDER=bedrock
OPS_AWS_REGION=us-west-2
OPS_BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-6
# credentials come from the standard AWS chain, or set AWS_BEARER_TOKEN_BEDROCK
```

`make preflight --list` prints the inference-profile ids your account can actually
invoke, which is the right way to pick that value — most current models are
profile-only, so the bare model id is not what you pass.

**Any Anthropic-compatible endpoint** — for development without Bedrock access:

```bash
OPS_MODEL_PROVIDER=anthropic
OPS_COMPAT_API_KEY=...
OPS_COMPAT_BASE_URL=https://...
OPS_COMPAT_MODEL_ID=...
```

Switching providers is one variable; `app/agent/model.py` is the only file that
knows the difference.

> **A note on the API surface.** The API reads customer records and approves refunds,
> so it is not a public endpoint. Set `OPS_API_TOKEN` to require a bearer token. Left
> unset it is unauthenticated — deliberately, so the demo runs with no setup — and the
> server logs a warning at startup saying so.

## Watching it work

The seed creates three live threads. Drive them from the command line:

```bash
cd backend

.venv/bin/python -m scripts.simulate_event booking     # a booking request
.venv/bin/python -m scripts.simulate_event complaint   # a refund request
.venv/bin/python -m scripts.simulate_event pending     # what is waiting on you
.venv/bin/python -m scripts.simulate_event approve --note "Agreed."
.venv/bin/python -m scripts.simulate_event followups   # the background sweep
```

### A booking, start to finish, with nobody watching

```
run run_350cffd9  completed
────────────────────────────────────────────────────────────────
  ✓ get_conversation           [LOW]
  ✓ get_customer_history       [LOW]
  ✓ calculate_price            [LOW]
  ✓ check_availability         [LOW]
  ✓ create_booking             [LOW]
  ✓ send_message               [MEDIUM]
  ✓ resolve_conversation       [LOW]

  Summary
  Amaka Eze messaged to upgrade her booking from standard to deep cleaning for
  her 3-bedroom flat next Saturday afternoon. Booked her in for Saturday
  12 September at 12:00 noon (BH-1045, NGN 20,000) and confirmed the details.
  Thread resolved.
```

`NGN 20,000` is not a number the model made up — `calculate_price` derived it from
the catalogue: a 15,000 deep clean plus two extra bedrooms at 2,500 each. The model
is not allowed to do that arithmetic, and the booking is written with the same
figure that was quoted.

### A complaint, where it stops

```
run run_9bf0496c  awaiting_approval
────────────────────────────────────────────────────────────────
  ✓ get_conversation           [LOW]
  ✓ get_business_policy        [LOW]
  ✓ get_booking                [LOW]
  ✓ get_customer_history       [LOW]
  ⏸ issue_refund               [HIGH]
      policy: require_approval — NGN 7,500.00 is above the NGN 5,000.00
      auto-approval limit, so it needs the owner.

  DECISION REQUIRED  apr_85021121
  Refund NGN 7,500.00 — BH-1041
  Recommended: Refund NGN 7,500.00 against booking BH-1041.
  Why: NGN 7,500.00 is above the NGN 5,000.00 auto-approval limit.
  Policy: refund approval band: 5000.0–60000.0
  · Booking BH-1041 (book_52856b96)
  · Customer record (cus_4492de06)
  · Customer conversation (conv_5ab2d764)
```

Note what is *not* in that list: `send_message`. The agent read the situation,
decided on a number, and stopped — it did not tell Sarah a refund was coming, because
no refund had been agreed. That rule is enforced too: outbound messages are blocked
while a decision on the same run is open.

### The owner answers, and the agent picks up mid-sentence

```bash
curl -X POST "localhost:8010/api/approvals/apr_85021121/decide?wait=true" \
  -H 'content-type: application/json' \
  -d '{"approved": true, "note": "Agreed. Also offer her a free oven clean on her next visit."}'
```

```
run run_9bf0496c  completed
  ✓ issue_refund               [HIGH]    ← the paused call, now authorised
  ✓ send_message               [MEDIUM]
  ✓ resolve_conversation       [LOW]
  ✓ update_customer            [LOW]

  Summary
  Issued a NGN 7,500 partial refund, which you approved, and confirmed it with her
  along with the free oven clean. Her customer notes are updated so the crew will
  know about the owed oven clean when she books again. Thread resolved.
```

The run did not start over. Strands persisted it at the interrupt and resumed the
same tool call. And the owner's *note* reached the agent, not just their verdict —
which is why an oven clean it was never asked to arrange ended up in the reply and in
the customer's record.

Reject it instead and the agent adapts rather than going quiet:

```bash
-d '{"approved": false, "note": "No. Half was fair. Offer a re-clean of the two bedrooms instead."}'
```

> Rather than an additional refund, what I can do is send the team back to re-clean
> the two bedrooms properly — skirting boards included — at no charge. You also still
> have the free oven clean we offered, so we can do both in one visit if that suits.

No refund row was written. The agent was told why, and did the thing it was told to do
instead.

### Work that happens with nobody watching

```bash
curl -X POST "localhost:8010/api/sweeps/follow-ups?wait=true"
```

```
threads due: 1
run run_5fd01ba7  completed
  ✓ get_conversation · calculate_price · send_message

  Sent Daniel Okoro a single nudge on his move-out clean quote (NGN 28,500) — he
  hadn't replied since Sep 1. Follow-up set for Sep 10; if he stays quiet, the
  thread will be resolved without a second chase.
```

Nobody asked for that. A quote had gone unanswered for four days, a schedule fired,
and the agent chased it once — then set itself a reminder to stop chasing.

## How it uses Strands

Not as a wrapper around a chat completion. The parts of the SDK that do real
structural work here:

- **`InterventionHandler`** — `app/policy/gate.py` is the enforcement point. It runs
  before every tool call and returns `Proceed`, `Deny`, or `Confirm`. This is the
  seam the whole product hangs off.
- **`Confirm` → interrupt** — returning `Confirm` without a preset response breaks
  the agent out of its loop with `stop_reason == "interrupt"`. That is the pause.
- **`SessionManager`** — `FileSessionManager` locally, `S3SessionManager` in AWS.
  Persists the paused run so it can be resumed in a different process, minutes or
  hours later. The approval flow is impossible without it.
- **Interrupt responses** — resuming with
  `[{"interruptResponse": {"interruptId": ..., "response": "yes"}}]` continues the
  *specific tool call* that stopped, not a fresh conversation about it.
- **`after_tool_call` + `Transform`** — when a confirmation is refused, Strands
  cancels the tool with a terse message. The gate rewrites that result to carry the
  owner's reasoning, so the agent gets "no, offer a re-clean instead" rather than
  just "no".
- **`HookProvider` / `AfterToolCallEvent`** — `app/agent/observer.py` writes the
  audit row for every executed call. The activity feed is generated from hook events,
  not from the model's self-report.
- **Tool docstrings as the contract** — 25 `@tool` functions across seven domains.
  The docstring is the model's only manual, so each one says when to reach for the
  tool and what not to do with it. A test enforces that they are substantive.

The SDK ships a `HumanInTheLoop` handler that pauses on the same primitive. It is not
used here because it gates on *tool identity* — an allow-list, or an LLM classifier —
and authority in this product is a function of the *arguments*:
`issue_refund(amount=2500)` is the agent's call and `issue_refund(amount=7500)` is not.
[docs/architecture.md](docs/architecture.md#why-not-the-built-in-humanintheloop-handler)
has the full reasoning.

`interrupt_id_for()` in the gate reproduces the id Strands will generate, so the
approval row exists *before* the run pauses and the owner's queue is never behind the
agent's state. A test pins that against the SDK's own `_interrupt_id`, so an upgrade
that changes the scheme fails loudly instead of silently orphaning approvals.

## Project layout

```
ops-agent/
├── backend/
│   ├── app/
│   │   ├── agent/          model factory, prompts, context, run lifecycle, audit hook
│   │   ├── policy/         risk table, policy engine, the intervention gate
│   │   ├── tools/          25 @tool functions — the agent's whole vocabulary
│   │   ├── services/       the only code that touches Postgres
│   │   ├── api/            FastAPI routes: events, approvals, dashboard data
│   │   └── db/             models, enums, session
│   ├── scripts/            init_db, seed, simulate_event, worker, preflight_bedrock
│   └── tests/              66 tests: policy, bookings, pricing, gate, resume, conversations
├── frontend/               Next.js dashboard — Today, Decisions, Activity, Rules
├── infrastructure/aws/     scoped IAM policy and the Bedrock notes
├── docs/                   architecture, design, tools, workflows, demo script
└── docker-compose.yml      Postgres
```

The API endpoints, in the order the owner meets them:

| | |
|---|---|
| `POST /api/messages` | a customer message arrives; wakes the agent |
| `POST /api/events` | any other trigger |
| `POST /api/sweeps/follow-ups` | the scheduled chase; what EventBridge calls |
| `GET /api/dashboard` | the whole home screen in one call |
| `GET /api/approvals` | the decision queue |
| `POST /api/approvals/{id}/decide` | approve or reject, and resume the run |
| `GET /api/runs` · `GET /api/runs/{id}` | the audit trail |
| `PUT /api/business/policies/{type}` | change what the agent is allowed to do |

Runs take 20–50 seconds, so the endpoints that start one return `202` and work in the
background by default. Pass `?wait=true` to get the finished run in the response, which
is what the scripts and the examples above do.

## Tests

```bash
make test    # 66 tests
make lint
```

They run against real Postgres inside a rolled-back transaction, so they exercise the
actual SQL and constraints. Three worth reading:

- `tests/test_policy.py` — the executable specification of what the agent may and may
  not do. Every band, ceiling and window, as an assertion.
- `tests/test_gate_resume.py` — an interrupt is re-execution, not continuation, so the
  gate's handler runs twice for one escalation. These drive both passes and assert the
  second writes nothing, and that a limit tightened mid-pause is applied on resume.
- `tests/test_gate.py` — the service layer still refuses an out-of-bounds write even if
  the gate were bypassed entirely, plus a check that the interrupt id we predict matches
  the one the SDK generates.

## Status

Working and verified end to end: the booking, reschedule, complaint/refund and
follow-up journeys; the approval pause and resume, including rejection with the owner's
reasoning; the audit trail; the policy engine and its API.

Still to come: Bedrock and AgentCore deployment, EventBridge scheduling, and the
supplier-invoice journey end to end — `record_supplier_invoice` exists and is tested,
but document extraction from S3 is not wired up yet.

On Bedrock specifically: credentials and the control plane work, but Anthropic and
OpenAI models are refused from this project's location by the providers' own country
policies, and the remaining models need a wider IAM grant than was first attached.
`make preflight` reports exactly which of those four things is in the way. The agent
runs on any Anthropic-compatible endpoint meanwhile, and switching is one variable —
see [infrastructure/aws](infrastructure/aws/README.md).

## License

MIT — see [LICENSE](LICENSE).
