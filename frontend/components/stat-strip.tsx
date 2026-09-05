import type { DashboardStats } from "@/lib/types";

import { Card } from "./ui";

/** The numbers the owner cares about, in the order they care about them.
 *
 *  "Handled without you" is first on purpose: it is the product's actual claim. The
 *  count of things waiting is second, because that is the only column that costs the
 *  owner time.
 */
export function StatStrip({ stats }: { stats: DashboardStats }) {
  const cells: { label: string; value: string | number; hint?: string; tone?: "wait" }[] = [
    {
      label: "Handled without you",
      value: stats.handled_without_you,
      hint: `of ${stats.runs} recent ${stats.runs === 1 ? "run" : "runs"}`,
    },
    {
      label: "Waiting on you",
      value: stats.awaiting_you,
      hint: stats.awaiting_you === 0 ? "nothing outstanding" : "decisions to make",
      tone: stats.awaiting_you > 0 ? "wait" : undefined,
    },
    { label: "Steps taken", value: stats.tool_calls, hint: "tool calls, all logged" },
    {
      label: "Jobs upcoming",
      value: stats.bookings_upcoming,
      hint: stats.overdue_tasks > 0 ? `${stats.overdue_tasks} task overdue` : `${stats.open_tasks} open tasks`,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cells.map((cell) => (
        <Card
          as="div"
          key={cell.label}
          className={
            cell.tone === "wait"
              ? "border-wait-border bg-wait-surface px-4 py-3"
              : "px-4 py-3"
          }
        >
          <p
            className={
              cell.tone === "wait"
                ? "text-[13px] font-medium text-wait-text"
                : "text-[13px] font-medium text-muted-foreground"
            }
          >
            {cell.label}
          </p>
          <p
            className={
              cell.tone === "wait"
                ? "tnum mt-0.5 text-[28px] font-semibold leading-none text-wait-text"
                : "tnum mt-0.5 text-[28px] font-semibold leading-none"
            }
          >
            {cell.value}
          </p>
          {cell.hint && (
            <p
              className={
                cell.tone === "wait"
                  ? "mt-1 text-[12px] text-wait-text/80"
                  : "mt-1 text-[12px] text-muted-foreground"
              }
            >
              {cell.hint}
            </p>
          )}
        </Card>
      ))}
    </div>
  );
}
