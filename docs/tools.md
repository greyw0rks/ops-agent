# Tools

25 tools across seven domains. The docstring is the model's only manual for a tool, so
each one says when to reach for it and what not to do with it — that text is the
interface, not decoration.

Risk levels come from `app/policy/risk.py`. A tool absent from that table is treated as
HIGH and denied.

## Customer

| Tool | Risk | Notes |
|---|---|---|
| `find_customer` | LOW | Matches on email, then phone, then name, and reports which identifier hit. Returns `ambiguous_name` with candidates rather than guessing. |
| `get_customer_history` | LOW | Bookings, threads, refunds, total refunded. One call, because judging a complaint needs all of it. |
| `create_customer` | LOW | Only after `find_customer` comes back empty. |
| `update_customer` | LOW | Whitelisted fields; anything else is reported in `rejected`. |

## Booking

| Tool | Risk | Notes |
|---|---|---|
| `check_availability` | LOW | Opening hours × concurrent capacity × what is already booked. The agent may not offer a slot this did not return. |
| `get_booking` | LOW | By internal id or by the reference a customer would quote. |
| `create_booking` | LOW | Re-checks capacity at write time, because availability goes stale. |
| `reschedule_booking` | LOW → gated | Notice window enforced; a third move needs the owner. |
| `cancel_booking` | MEDIUM → gated | Inside the free window a fee is at stake, so the owner decides. |

## Business

| Tool | Risk | Notes |
|---|---|---|
| `get_service_catalog` | LOW | Turns "a deep clean" into a real `service_id`. |
| `find_service` | LOW | Loose match for when the catalogue mapping isn't obvious. |
| `get_business_policy` | LOW | The owner's rules, also quotable back to a customer. |
| `calculate_price` | LOW | Only modifiers the service declares are chargeable, so a line item cannot be invented. |

## Communication

| Tool | Risk | Notes |
|---|---|---|
| `get_conversation` | LOW | Defaults to the thread that triggered the run. |
| `send_message` | MEDIUM → gated | Denied while a decision on the same run is open. Identical bodies inside five minutes are suppressed. |
| `resolve_conversation` | LOW | Stops the follow-up sweep looking at a settled thread. |

## Operations

| Tool | Risk | Notes |
|---|---|---|
| `create_task` | LOW | The agent's way of handing work to a person. |
| `get_open_tasks` | LOW | Checked before creating, to avoid duplicates. |
| `update_task` | LOW | |
| `complete_task` | LOW | Only when the work is actually finished. |

## Billing

| Tool | Risk | Notes |
|---|---|---|
| `issue_refund` | HIGH → gated | Bands from the refund policy. One per run. Cannot exceed what was paid. Refused outside the claim window. |
| `apply_discount` | MEDIUM → gated | Percentage bands from the discount policy. |
| `record_supplier_invoice` | LOW | Refuses a duplicate supplier + reference pair. |

## Approval

| Tool | Risk | Notes |
|---|---|---|
| `request_approval` | LOW | The agent asking for a human on its own initiative. Always honoured — calling it pauses the run, and the body only executes once someone has decided. |
| `get_approval_status` | LOW | |

## Conventions

**Structured returns.** Every tool returns a dict, never prose. `{"available": true,
"slots": [...]}` is testable and cheap in context; a paragraph is neither.

**Failures are values.** A tool that cannot do its job returns `{"ok": false, "error":
"..."}` rather than raising, so the agent can adapt instead of the run dying. Genuine
exceptions are recorded against the run and surface as a failed run.

**No `business_id` parameter.** Tools read it from the run context
(`app/tools/_context.py`), because a tenant id the model can set is a tenant id the
model can change.

**Reason strings are written for the owner.** `"NGN 7,500.00 is above the NGN 5,000.00
auto-approval limit"` appears verbatim on the approval card. It is not log output.
