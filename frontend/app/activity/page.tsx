"use client";

import { useMemo, useState } from "react";

import { useChrome } from "@/components/app-shell";
import { RunItem } from "@/components/run-item";
import { PageTitle } from "@/components/shell";
import { Button, Card, EmptyState, ErrorNote, SectionHeader, Skeleton, cx } from "@/components/ui";
import { api } from "@/lib/api";
import type { RunStatus } from "@/lib/types";
import { usePoll } from "@/lib/use-poll";

const FILTERS: { key: "all" | RunStatus; label: string }[] = [
  { key: "all", label: "Everything" },
  { key: "completed", label: "Handled" },
  { key: "awaiting_approval", label: "Waiting on you" },
  { key: "failed", label: "Failed" },
];

export default function ActivityPage() {
  const { currency } = useChrome();
  const [filter, setFilter] = useState<"all" | RunStatus>("all");
  const { data, error, loading, refresh, refreshing } = usePoll(() => api.runs(60), 5000);

  const runs = useMemo(() => {
    const all = data?.runs ?? [];
    return filter === "all" ? all : all.filter((run) => run.status === filter);
  }, [data, filter]);

  const totals = useMemo(() => {
    const all = data?.runs ?? [];
    return {
      steps: all.reduce((sum, run) => sum + run.action_count, 0),
      escalated: all.filter((run) =>
        (run.actions ?? []).some((action) => action.policy_decision !== "allow"),
      ).length,
    };
  }, [data]);

  if (error) return <ErrorNote message={error} />;

  return (
    <>
      <PageTitle
        title="Activity"
        lede="Every time the agent woke up, every tool it called, and what your rules decided about each one. Generated from the record, not from the agent's account of itself."
      />

      {loading ? (
        <Skeleton className="h-96" />
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            {FILTERS.map((option) => {
              const count =
                option.key === "all"
                  ? (data?.runs.length ?? 0)
                  : (data?.runs.filter((run) => run.status === option.key).length ?? 0);
              if (count === 0 && option.key !== "all") return null;
              return (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => setFilter(option.key)}
                  className={cx(
                    "rounded-md border px-2.5 py-1 text-[13px] font-medium transition-colors duration-150",
                    filter === option.key
                      ? "border-primary bg-accent text-accent-foreground"
                      : "bg-background text-muted-foreground hover:bg-muted",
                  )}
                >
                  {option.label} <span className="tnum">{count}</span>
                </button>
              );
            })}
            <Button
              tone="quiet"
              size="sm"
              onClick={() => void refresh()}
              className="ml-auto"
              disabled={refreshing}
            >
              {refreshing ? "Refreshing…" : "Refresh"}
            </Button>
          </div>

          <Card>
            <SectionHeader
              title="Runs"
              count={runs.length}
              hint={`${totals.steps} steps in total · ${totals.escalated} needed you`}
            />
            {runs.length === 0 ? (
              <EmptyState
                glyph="—"
                title="No runs here"
                body={
                  filter === "all"
                    ? "Nothing has woken the agent yet."
                    : "Try a different filter."
                }
              />
            ) : (
              <div>
                {runs.map((run, index) => (
                  <RunItem
                    key={run.run_id}
                    run={run}
                    currency={currency}
                    defaultOpen={index === 0 && filter !== "all"}
                  />
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
