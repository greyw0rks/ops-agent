# Ops Agent — AWS Agents for Humans Hackathon Submission

**Track:** Professional Agents  
**Submitted by:** greyw0rks  
**Repository:** https://github.com/greyw0rks/ops-agent  
**Demo Video:** [Coming soon]

---

## What it does

Ops Agent is an autonomous operations assistant for small service businesses. It handles the repetitive operational work — booking requests, reschedules, simple refunds, follow-ups — and only interrupts the owner when there's a genuine decision to make.

**The key insight:** An agent that can spend money needs two different kinds of thinking. A language model is good at *"What should happen here?"* — but *"Is the agent allowed to do that?"* is a question about authority, and that answer must come from the application, not the model.

So the two are separate layers:

```
model proposes  →  application rules  →  human decides (if needed)  →  service executes
```

The limits live in `business_policies` rows the owner controls. They're read by a policy engine and enforced by a Strands `InterventionHandler` that runs **before** the tool function is entered. Nothing in a customer's message can move them — including a message that asks nicely.

## What makes it a Professional Agent

1. **Authority is enforced in code, not in the prompt**  
   The model decides what should happen. The application decides whether it's allowed. A refund above the owner's limit pauses the run; the model never sees the money.

2. **The agent does real work, not conversation**  
   Every run is recorded: which event woke it, which tools it called, what the policy engine decided, what the owner chose. The dashboard shows work that happened, not a transcript.

3. **Pause and resume with context**  
   When approval is needed, the run stops mid-sentence. The owner's decision — including their reasoning — reaches the agent, and it resumes at the exact tool call. No retries, no starting over.

4. **It works when nobody's watching**  
   A quote goes unanswered for four days. A schedule fires, the agent reads the thread, sends a nudge, and sets a reminder to stop chasing. That's the difference between an operations agent and a chatbot.

5. **Built for Bedrock and production AWS**  
   Session persistence uses S3SessionManager. Model provider is a one-variable switch. EventBridge scheduler drives the background sweeps. The whole thing is designed to run on ECS Fargate with Bedrock as the inference backend.

## Architecture

```
Customer message  →  FastAPI /api/events  →  AgentRun opened
                                              ↓
                                     ┌────────────────┐
                                     │  Strands Agent │
                                     │  Bedrock/Claude│
                                     └────────┬───────┘
                                              ↓
                                     ┌────────────────┐
                                     │  PolicyGate    │
                                     │  (Intervention │
                                     │   Handler)     │
                                     └────────┬───────┘
                                              ↓
                              ┌───────────────┼───────────────┐
                              │               │               │
                           Proceed          Deny          Confirm
                              ↓               ↓               ↓
                         Tool runs      Refused         Paused
                              ↓                              ↓
                       Service layer                Owner approves
                              ↓                              ↓
                         Postgres  ←────────────────  Agent resumes
```

**Key Strands SDK features used:**

- `InterventionHandler` — the enforcement point that gates every tool call
- `Confirm` → interrupt — pausing a run when approval is needed
- `SessionManager` (S3 in production) — persisting paused state across processes
- Interrupt responses — resuming with the owner's reasoning, not just their yes
- `after_tool_call` + `Transform` — rewriting rejection messages to carry context
- `HookProvider` / `AfterToolCallEvent` — the audit trail is generated from hooks, not from the model's self-report

## What it handles

| Action | Autonomous | Asks first |
|--------|------------|------------|
| New booking requests | ✅ identify, price, schedule, confirm | |
| Reschedules with notice | ✅ | |
| Small refunds inside the owner's limit | ✅ | |
| Refunds above that limit | | ⏸ owner decides, agent resumes |
| Late cancellations where a fee is at stake | | ⏸ waiving it is the owner's call |
| Discounts beyond pre-authorised percentage | | ⏸ |
| Quotes nobody answered | ✅ one nudge, then stops | |
| Supplier invoices | ✅ files them, flags duplicates | |
| Anything above the owner's ceiling | | ❌ refused, task opened instead |

## Technical Highlights

**25 tools across 7 domains:**
- Conversations (customer threads)
- Bookings (scheduling, capacity, customer history)
- Billing (refunds, discounts, supplier invoices)
- Business (policies, working hours, catalogue)
- Customers (notes, preferences)
- Operations (tasks, handovers)
- Communication (messages, templates)

**Policy-gated execution:**
- Refund limits: auto-approve below, require approval up to ceiling, deny above
- Discount limits: by percentage
- Cancellation windows: free vs. fee-bearing
- Rescheduling: free reschedules vs. requires notice
- Outbound messaging: blocked while a decision on the same run is open

**Production-ready infrastructure:**
- Postgres for durable state
- S3 for paused session storage (survives ECS task restarts)
- EventBridge scheduler for background sweeps
- CloudWatch logs with structured logging
- Health checks and graceful shutdown
- IAM policies scoped to exactly what the agent needs

**66 tests**, including:
- Policy engine spec (every band, ceiling, window)
- Gate re-execution caveat (interrupt handlers run twice)
- Service layer refuses out-of-bounds writes even if gate is bypassed
- Interrupt ID prediction matches SDK's actual ID
- Pricing derived from catalogue, not model arithmetic
- Double-booking prevention in concurrent writes

## Demo Flow

**1. Booking request (no approval needed)**
```bash
python -m scripts.simulate_event booking
```
Amaka wants a deep clean for Saturday. The agent checks her history, calculates the price from the catalogue (not by LLM arithmetic), checks availability, books it, confirms. Thread resolved. Nobody approved anything — that's the intended state.

**2. Complaint (approval required)**
```bash
python -m scripts.simulate_event complaint
```
Sarah's clean went badly. The agent reads the thread, pulls the booking, checks the refund policy, pulls her history — then **stops**. NGN 7,500 is above the NGN 5,000 auto-approval limit.

Note what's missing from the tool list: `send_message`. The agent decided on a number and said nothing to the customer, because nothing had been agreed.

**3. Owner approves with a note**
```bash
python -m scripts.simulate_event approve --note "Agreed. Also offer her a free oven clean."
```
The run resumes at the same tool call. The refund is written stamped with the approval that authorized it. The reply mentions the oven clean, and Sarah's customer record now says the crew owes her one — from a one-line note.

**4. Background sweep (nobody watching)**
```bash
python -m scripts.simulate_event followups
```
Daniel's quote has been unanswered for four days. A schedule fired, the agent read the thread, decided a nudge was warranted, sent one, set a reminder to stop chasing.

## Why it works

**Defence in depth:**
1. Policy engine enforces limits before tool entry
2. Prompt tells the agent limits exist and aren't negotiable
3. Risk table where unknown tools fail closed
4. Service layer independently raises `PolicyViolation` without an approval ID
5. One refund per run (idempotency)
6. Outbound messaging independently gated

**Audit trail:**
Every run, every tool call, what the policy engine decided, which human approved what. The owner's question is never "what did the AI say" — it's "what was done to my business, and who let it happen", and that has an answer in Postgres.

**Real deployment path:**
The README status says "Bedrock and AgentCore deployment" is still to come, but the infrastructure is ready:
- `OPS_MODEL_PROVIDER=bedrock` is a one-variable switch
- S3SessionManager wired up and tested
- IAM policies scoped and documented
- ECS task definition ready
- EventBridge scheduler config included
- See [infrastructure/aws/agentcore-deployment.md](infrastructure/aws/agentcore-deployment.md) for full deployment guide

## What's Unique

Most agent demos show a chatbot that can call a payment API. This goes further:

1. **Authority lives in the application layer** — policy as code, not as a system prompt the model can be talked out of

2. **Pause/resume is first-class** — the owner's reasoning reaches the agent, not just their yes/no. A rejected refund becomes "offer a re-clean instead" without the agent starting over.

3. **The agent is trusted with repetitive work precisely because it's not trusted with the money** — that's the trade that makes autonomous operation safe enough to deploy.

4. **It's built for production AWS, not just a demo** — Strands on Bedrock, paused runs in S3, EventBridge for scheduling, ECS for serving, all the boring infrastructure that makes "autonomous" mean "runs when you're asleep".

## Tech Stack

**Backend:**
- Python 3.12
- FastAPI
- Strands Agents SDK
- Postgres (SQLAlchemy)
- Amazon Bedrock (Claude Sonnet)
- boto3 (S3, Bedrock)

**Frontend:**
- Next.js 15
- React 19
- Tailwind CSS
- Recharts (dashboard metrics)

**Infrastructure:**
- Docker
- AWS ECS Fargate
- AWS RDS Postgres
- AWS S3
- AWS EventBridge
- AWS CloudWatch
- AWS IAM

## Running Locally

```bash
# Prerequisites: Docker, Python 3.12+, uv
git clone https://github.com/greyw0rks/ops-agent.git
cd ops-agent

# Configure model provider
cp .env.example .env
# Set OPS_MODEL_PROVIDER=bedrock or anthropic, see README

# Start Postgres, install deps, init DB, seed demo data
make db-up
make install
make init-db
make seed

# Start API
make api         # http://localhost:8010/docs

# Start dashboard (separate terminal)
make web-install
make web         # http://localhost:3010

# Drive it from the CLI
cd backend
.venv/bin/python -m scripts.simulate_event booking
.venv/bin/python -m scripts.simulate_event complaint
.venv/bin/python -m scripts.simulate_event approve --note "Agreed."
.venv/bin/python -m scripts.simulate_event followups
```

## Tests

```bash
make test    # 66 tests, ~6 seconds
make lint    # ruff check
```

All tests run against real Postgres inside a rolled-back transaction, so they exercise actual SQL and constraints.

## Documentation

- [README.md](README.md) — project overview, quickstart, architecture
- [docs/architecture.md](docs/architecture.md) — why each boundary is where it is, pause/resume mechanics, the intervention handler
- [docs/design.md](docs/design.md) — the three concerns kept deliberately apart, defence in depth
- [docs/tools.md](docs/tools.md) — the 25 tools the agent knows, grouped by domain
- [docs/workflows.md](docs/workflows.md) — booking, complaint, follow-up journeys
- [docs/demo.md](docs/demo.md) — 5-minute demo script, four beats
- [infrastructure/aws/README.md](infrastructure/aws/README.md) — Bedrock setup, IAM policies, preflight check
- [infrastructure/aws/agentcore-deployment.md](infrastructure/aws/agentcore-deployment.md) — full ECS + Bedrock deployment guide

## Limitations and Future Work

**Current scope:**
- Demo seeded with one business (BrightHome Services, Lagos)
- Single-tenant (no multi-business isolation yet)
- English only
- Nigerian Naira (NGN) hardcoded
- EventBridge scheduler config documented but not deployed
- Supplier invoice document extraction not wired up (tool exists, S3 trigger missing)

**Future enhancements:**
- Multi-business support with tenant isolation
- WhatsApp Business API integration (currently simulated)
- Email integration (IMAP/SMTP)
- Supplier invoice OCR via Textract
- Payment processing integration
- Calendar sync (Google Calendar, iCal)
- SMS notifications
- Multi-currency support
- Localization (i18n)

## Cost to Run

Production deployment on AWS (us-west-2):
- ECS Fargate (0.5 vCPU, 1GB RAM, 24/7): ~$15/month
- RDS Postgres t4g.micro: ~$15/month
- S3 session storage: <$1/month
- Bedrock Claude Sonnet (~100 runs/day): ~$20-40/month
- **Total: ~$60-90/month**

RDS Serverless v2 can reduce database costs to ~$10-20/month.

## Why This Matters

A three-person cleaning company in Lagos takes bookings by WhatsApp and email. Every one is five minutes of lookup-check-price-write-reply. Then there are the reschedules, the quotes nobody answered, the supplier invoices, the occasional complaint.

None of it is hard. All of it has to happen. It happens in the evening, after the actual work, and it's why the owner hasn't taken a day off since March.

The parts that genuinely need a human are a small fraction — and they're the parts that get the least attention, because they're buried in the rest.

This agent does the repetitive work autonomously, pauses for the real decisions, and leaves an audit trail of what it did and who authorized it.

That's the trade: the agent is trusted with the work precisely because it's not trusted with the money.

---

**Built with:**
- [Strands Agents SDK](https://strandsagents.com)
- [Amazon Bedrock](https://aws.amazon.com/bedrock/)
- Claude Sonnet (Anthropic)

**License:** MIT
