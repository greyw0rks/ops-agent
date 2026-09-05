# Demo script

Five minutes, four beats. The point to land is not "an AI replied to an email" — it is
that the agent did the work, and knew which part wasn't its to do.

## Setup

```bash
make db-up && make install && make init-db && make seed && make api
```

The seed creates **BrightHome Services** (Lagos, NGN, four services, three customers
with real history) and three live threads:

| Thread | Customer | Situation |
|---|---|---|
| booking request | Amaka Eze | wants a clean for Saturday afternoon |
| complaint | Sarah Johnson | yesterday's NGN 15,000 deep clean went badly |
| stale quote | Daniel Okoro | quoted NGN 28,500 four days ago, went quiet |

## Beat 1 — the problem (40s)

Show the inbox, not the app. Three messages, each five minutes of the same
lookup-check-price-write-reply. Say the number: a few hundred of these a month, all of
them after hours.

Then the honest framing: most of it should not need a person, and the small part that
does is currently getting the least attention because it is buried in the rest.

## Beat 2 — the agent does the work (70s)

```bash
.venv/bin/python -m scripts.simulate_event booking
```

Let the tool list scroll. Then point at three specific things:

- `calculate_price` before `create_booking` — **NGN 10,500 is derived from the
  catalogue**, a 7,500 clean plus two extra bedrooms at 1,500. The model is not allowed
  to do that arithmetic.
- `check_availability` before the booking — it offered 1:00 PM because that slot was
  genuinely free, and the write re-checks capacity in case it filled up meanwhile.
- The reply itself — `GET /api/conversations/{id}` shows the thread. Name, day, local
  time, price, reference. Four specifics, no padding.

Nobody approved anything. That is the intended state for the large majority of runs.

## Beat 3 — the agent knows what isn't its to decide (110s)

The centrepiece.

```bash
.venv/bin/python -m scripts.simulate_event complaint
```

It reads the thread, pulls the booking, reads the **refund policy**, pulls Sarah's
history — then stops.

```
⏸ issue_refund   [HIGH]
    policy: require_approval — NGN 7,500.00 is above the NGN 5,000.00
    auto-approval limit, so it needs the owner.
```

Two things to say out loud here:

**The limit is not in the prompt.** It is a row in `business_policies` that the owner
edits, read by a policy engine, enforced by an intervention that runs before the tool
function is entered. Nothing in Sarah's message could have moved it — including a
message that asked the agent nicely to move it.

**Look at what is missing from that list: `send_message`.** The agent decided on a
number and said nothing to the customer, because nothing had been agreed. That rule is
enforced too.

Then approve it, with a note:

```bash
.venv/bin/python -m scripts.simulate_event approve \
  --note "Agreed. Also offer her a free oven clean on her next visit."
```

The run **resumes at the same tool call** — it does not start over; Strands persisted
it at the interrupt. The refund is written stamped with the approval that authorised
it. And the reply mentions the oven clean, and Sarah's customer record now says the
crew owes her one — from a one-line note, because the owner's *reasoning* reaches the
agent, not just their yes.

If there is time, reject one instead and show it offering a re-clean rather than going
quiet.

## Beat 4 — it works with nobody watching (50s)

```bash
.venv/bin/python -m scripts.simulate_event followups
```

Daniel's quote has been unanswered for four days. A schedule fired, the agent read the
thread, decided a nudge was warranted, sent one, and set a reminder to stop chasing.

Nobody was in the room. That is the difference between an operations agent and a
chatbot.

## Beat 5 — why it matters (30s)

The audit trail: `GET /api/runs`. Every run, every tool call, what the policy engine
decided, which human approved what. The owner's question is never "what did the AI say"
— it is "what was actually done to my business, and who let it happen", and that has an
answer in Postgres.

Close on the trade the product is really making: the agent is trusted with the
repetitive work precisely because it is not trusted with the money.

## Notes for recording

- `?wait=true` on the API endpoints if you would rather drive it with curl.
- Runs take 20–50 seconds. Cut the dead air, or narrate the tool list as it fills.
- Have `make api` up so `/docs` and `GET /api/dashboard` are available on screen.
- Reset between takes: `make reset-db && rm -rf backend/.sessions`.
