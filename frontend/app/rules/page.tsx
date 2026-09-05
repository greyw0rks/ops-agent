"use client";

import { PolicyEditor, type PolicySpec } from "@/components/policy-editor";
import { PageTitle } from "@/components/shell";
import { Pill } from "@/components/status";
import { Card, ErrorNote, SectionHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { usePoll } from "@/lib/use-poll";

/** The four policies, with the rule keys the engine actually reads. Labels are the
 *  owner's words; the keys underneath are what `app/policy/engine.py` looks up. */
const POLICIES: PolicySpec[] = [
  {
    type: "refund",
    title: "Refunds",
    lede: "The agent sizes a refund from the situation. These numbers decide what happens to that figure.",
    fields: [
      {
        key: "auto_approve_below",
        label: "Refund on its own, under",
        unit: "money",
        help: "Below this the agent just does it and logs it.",
      },
      {
        key: "approval_required_below",
        label: "Ask you, up to",
        unit: "money",
        help: "Between the two figures the run pauses and comes to you.",
      },
      {
        key: "manual_review_above",
        label: "Refuse outright above",
        unit: "money",
        help: "Above this the agent will not even propose it — it opens a task for you instead.",
      },
      {
        key: "window_days",
        label: "Claims accepted within",
        unit: "days",
        help: "Measured from the end of the job.",
      },
    ],
  },
  {
    type: "discount",
    title: "Discounts",
    lede: "Goodwill on an upcoming job, where a refund is the wrong instrument.",
    fields: [
      {
        key: "auto_approve_percent",
        label: "Discount on its own, up to",
        unit: "percent",
        help: "Pre-authorised.",
      },
      {
        key: "approval_required_percent",
        label: "Ask you, up to",
        unit: "percent",
        help: "Above the first figure and up to this one, you decide.",
      },
      {
        key: "manual_review_above_percent",
        label: "Refuse outright above",
        unit: "percent",
        help: "Beyond this it is yours alone.",
      },
    ],
  },
  {
    type: "cancellation",
    title: "Cancellations",
    lede: "Whether a customer pays for cancelling late — and who gets to waive it.",
    fields: [
      {
        key: "free_cancellation_hours",
        label: "Free with notice of",
        unit: "hours",
        help: "With at least this much notice the agent cancels without asking.",
      },
      {
        key: "late_cancellation_fee_percent",
        label: "Late fee",
        unit: "percent",
        help: "Inside the window this applies, and the agent asks you before charging or waiving it.",
      },
    ],
  },
  {
    type: "rescheduling",
    title: "Rescheduling",
    lede: "How much moving around the agent absorbs before it involves you.",
    fields: [
      {
        key: "free_reschedules",
        label: "Moves without asking",
        unit: "count",
        help: "Per booking. The next one comes to you.",
      },
      {
        key: "min_notice_hours",
        label: "Minimum notice",
        unit: "hours",
        help: "Inside this the agent refuses the move and offers alternatives.",
      },
    ],
  },
];

export default function RulesPage() {
  const { data, error, loading, refresh } = usePoll(api.business, 30_000);

  if (error) return <ErrorNote message={error} />;
  if (loading || !data) {
    return (
      <>
        <PageTitle title="Rules" />
        <Skeleton className="h-96" />
      </>
    );
  }

  return (
    <>
      <PageTitle
        title="Rules"
        lede="The limits the agent works within. These are rows in the database, read by the policy engine before every consequential action — not instructions in a prompt. Change one and it applies to the agent's very next step."
      />

      <div className="space-y-6">
        {POLICIES.map((policy) => (
          <PolicyEditor
            key={policy.type}
            spec={policy}
            business={data}
            onSaved={() => void refresh()}
          />
        ))}

        <Card>
          <SectionHeader title="What the agent is told about itself" />
          <div className="space-y-3 px-5 py-4 text-[15px] leading-normal">
            <p>
              The prompt says the limits above exist, that they are enforced by the application
              rather than by the agent, and that it should call the tool that does the right thing
              and let itself be stopped.
            </p>
            <p className="text-muted-foreground">
              That wording is deliberate. An agent asked to police itself has a reason to
              rationalise; an agent that knows it will be stopped has none. Nothing a customer
              writes can move these numbers, because nothing a customer writes is consulted when
              they are read.
            </p>
            <div className="flex flex-wrap gap-2 pt-1">
              <Pill tone="info">{data.agent.provider}</Pill>
              <span className="ident text-muted-foreground">{data.agent.model_id}</span>
            </div>
          </div>
        </Card>

        <Card>
          <SectionHeader title="Service catalogue" count={data.catalog.length} />
          <ul>
            {data.catalog.map((service) => (
              <li
                key={service.service_id}
                className="flex flex-wrap items-baseline justify-between gap-2 border-b px-5 py-2.5 last:border-b-0"
              >
                <div className="min-w-0">
                  <p className="text-[15px]">{service.name}</p>
                  <p className="text-[13px] text-muted-foreground">
                    {service.duration_minutes} min
                    {Object.entries(service.price_modifiers).map(([key, value]) => (
                      <span key={key}>
                        {" · "}
                        {money(value, data.currency)} per extra {key.replace(/s$/, "")}
                      </span>
                    ))}
                  </p>
                </div>
                <p className="tnum text-[15px]">{money(service.base_price, data.currency)}</p>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
