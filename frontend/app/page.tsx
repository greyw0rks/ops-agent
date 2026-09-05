"use client";

import Link from "next/link";

import { DecisionCard } from "@/components/decision-card";
import { RunItem } from "@/components/run-item";
import { PageTitle } from "@/components/shell";
import { StatStrip } from "@/components/stat-strip";
import { Card, EmptyState, ErrorNote, SectionHeader, Skeleton } from "@/components/ui";
import { useChrome } from "@/components/app-shell";
import { api } from "@/lib/api";
import { ago, dayTime, money } from "@/lib/format";
import { usePoll } from "@/lib/use-poll";

export default function TodayPage() {
  const { refreshChrome } = useChrome();
  const { data, error, loading, refresh } = usePoll(api.dashboard, 4000);

  if (error) return <ErrorNote message={error} />;

  if (loading || !data) {
    return (
      <>
        <PageTitle title="Today" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[92px]" />
          ))}
        </div>
        <Skeleton className="mt-6 h-56" />
      </>
    );
  }

  const currency = data.business.currency;

  function onDecided() {
    void refresh();
    refreshChrome();
  }

  return (
    <>
      <PageTitle
        title="Today"
        lede={`${data.business.name} — what the agent has been doing, and the small part it needs you for.`}
      />

      <StatStrip stats={data.stats} />

      <div className="mt-6 space-y-6">
        {data.needs_you.length > 0 && (
          <section>
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="text-[17px] font-semibold tracking-tight">
                Needs you{" "}
                <span className="tnum font-normal text-muted-foreground">
                  {data.needs_you.length}
                </span>
              </h2>
              {data.needs_you.length > 1 && (
                <Link href="/decisions" className="text-[14px] text-primary hover:underline">
                  See all decisions
                </Link>
              )}
            </div>
            <div className="space-y-3">
              {data.needs_you.slice(0, 2).map((approval) => (
                <DecisionCard
                  key={approval.approval_id}
                  approval={approval}
                  onDecided={onDecided}
                />
              ))}
            </div>
          </section>
        )}

        <Card>
          <SectionHeader
            title="What the agent did"
            count={data.activity.length}
            action={
              <Link href="/activity" className="text-[14px] text-primary hover:underline">
                Full history
              </Link>
            }
          />
          {data.activity.length === 0 ? (
            <EmptyState
              glyph="—"
              title="Nothing yet"
              body="Send the agent a customer message and its work will appear here."
            />
          ) : (
            <div>
              {data.activity.slice(0, 6).map((run) => (
                <RunItem key={run.run_id} run={run} currency={currency} />
              ))}
            </div>
          )}
        </Card>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <SectionHeader title="Next jobs" count={data.upcoming_bookings.length} />
            {data.upcoming_bookings.length === 0 ? (
              <EmptyState glyph="—" title="Nothing on the calendar" />
            ) : (
              <ul>
                {data.upcoming_bookings.map((booking) => (
                  <li
                    key={booking.booking_id}
                    className="flex items-baseline justify-between gap-3 border-b px-5 py-2.5 last:border-b-0"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-[15px]">{booking.service_name}</p>
                      <p className="text-[13px] text-muted-foreground">
                        {dayTime(booking.starts_at)}
                        {booking.created_by === "agent" && " · booked by the agent"}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="tnum text-[15px]">{money(booking.price, currency)}</p>
                      <p className="ident text-muted-foreground">{booking.reference}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <SectionHeader title="On your list" count={data.open_tasks.length} />
            {data.open_tasks.length === 0 ? (
              <EmptyState glyph="✓" title="Nothing outstanding" />
            ) : (
              <ul>
                {data.open_tasks.map((task) => (
                  <li key={task.task_id} className="border-b px-5 py-2.5 last:border-b-0">
                    <p className="text-[15px] leading-snug">{task.title}</p>
                    <p className="mt-0.5 text-[13px] text-muted-foreground">
                      {task.due_at ? `due ${dayTime(task.due_at)}` : "no due date"}
                      {task.created_by === "agent" && " · opened by the agent"}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        {data.recent_refunds.length > 0 && (
          <Card>
            <SectionHeader
              title="Money out"
              count={data.recent_refunds.length}
              hint="Every refund is stamped with the decision that authorised it"
            />
            <ul>
              {data.recent_refunds.map((refund) => (
                <li
                  key={refund.refund_id}
                  className="flex flex-wrap items-baseline justify-between gap-2 border-b px-5 py-2.5 last:border-b-0"
                >
                  <div className="min-w-0">
                    <p className="tnum text-[15px]">{money(refund.amount, currency)}</p>
                    <p className="line-clamp-2 text-[13px] text-muted-foreground">
                      {refund.reason ?? "no reason recorded"}
                    </p>
                  </div>
                  <div className="text-right text-[13px] text-muted-foreground">
                    <p>{ago(refund.created_at)}</p>
                    <p className="ident">{refund.approval_id ?? "no approval needed"}</p>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </>
  );
}
