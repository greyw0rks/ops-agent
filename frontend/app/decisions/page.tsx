"use client";

import { DecisionCard } from "@/components/decision-card";
import { PageTitle } from "@/components/shell";
import { Card, EmptyState, ErrorNote, SectionHeader, Skeleton } from "@/components/ui";
import { useChrome } from "@/components/app-shell";
import { Pill } from "@/components/status";
import { api } from "@/lib/api";
import { ago, money, titleCase } from "@/lib/format";
import { usePoll } from "@/lib/use-poll";

export default function DecisionsPage() {
  const { refreshChrome } = useChrome();
  const pending = usePoll(() => api.approvals("pending"), 5000);
  const settled = usePoll(() => api.approvals(null), 20_000);

  if (pending.error) return <ErrorNote message={pending.error} />;

  const decided = (settled.data?.approvals ?? []).filter(
    (approval) => approval.status !== "pending",
  );

  return (
    <>
      <PageTitle
        title="Decisions"
        lede="The agent stops at anything outside the authority you gave it. Answering here resumes the run at the exact step it paused on."
      />

      {pending.loading ? (
        <Skeleton className="h-72" />
      ) : pending.data && pending.data.approvals.length > 0 ? (
        <div className="space-y-4">
          {pending.data.approvals.map((approval) => (
            <DecisionCard
              key={approval.approval_id}
              approval={approval}
              onDecided={() => {
                void pending.refresh();
                void settled.refresh();
                refreshChrome();
              }}
            />
          ))}
        </div>
      ) : (
        <Card>
          <EmptyState
            glyph="✓"
            title="Nothing waiting on you"
            body="The agent is handling everything inside your limits. It will interrupt only when it hits one."
          />
        </Card>
      )}

      {decided.length > 0 && (
        <Card className="mt-8">
          <SectionHeader
            title="Already decided"
            count={decided.length}
            hint="Kept so you can see what you agreed to and when"
          />
          <ul>
            {decided.map((approval) => (
              <li key={approval.approval_id} className="border-b px-5 py-3 last:border-b-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Pill
                    tone={approval.status === "approved" ? "ok" : "deny"}
                    glyph={approval.status === "approved" ? "✓" : "⊘"}
                  >
                    {titleCase(approval.status)}
                  </Pill>
                  <span className="text-[15px] font-medium">{approval.title}</span>
                  {approval.amount !== null && (
                    <span className="tnum text-[14px] text-muted-foreground">
                      {money(approval.amount, approval.currency ?? "NGN")}
                    </span>
                  )}
                  <span className="ml-auto text-[13px] text-muted-foreground">
                    {ago(approval.decided_at)}
                  </span>
                </div>
                {approval.decision_note && (
                  <p className="mt-1 border-l-2 border-border pl-3 text-[14px] italic text-muted-foreground">
                    &ldquo;{approval.decision_note}&rdquo;
                  </p>
                )}
                <p className="mt-1 text-[13px] text-muted-foreground">
                  {approval.recommended_action}
                </p>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
