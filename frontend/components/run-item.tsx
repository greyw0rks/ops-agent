"use client";

import { useState } from "react";

import { ago, duration, humanTool, triggerLabel } from "@/lib/format";
import type { AgentRun } from "@/lib/types";

import { describeAction } from "./describe-action";
import { ActionStatusMark, PolicyNote, RiskPill, RunStatusPill } from "./status";
import { cx } from "./ui";

/** One agent run in the activity feed.
 *
 *  Collapsed it answers "what happened and did it need me". Expanded it shows every
 *  tool call and what the policy engine decided about each one — which is the whole
 *  argument for trusting the thing, so it is one click away rather than buried.
 */
export function RunItem({
  run,
  currency = "NGN",
  defaultOpen = false,
}: {
  run: AgentRun;
  currency?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const actions = run.actions ?? [];
  const escalated = actions.some((action) => action.policy_decision !== "allow");

  // A paused run has no closing summary yet — it stopped mid-sentence. Say what it is
  // stuck on instead of leaving the row blank, since "why is this waiting" is the only
  // question the owner has about it.
  const pausedOn =
    run.status === "awaiting_approval"
      ? actions.find((action) => action.status === "awaiting_approval")?.policy_reason
      : null;
  const blurb = run.summary ?? pausedOn ?? null;

  return (
    <div className="border-b last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors duration-150 hover:bg-muted/60"
      >
        <span
          aria-hidden
          className={cx(
            "mt-1 w-3 shrink-0 text-[11px] text-muted-foreground transition-transform duration-150",
            open && "rotate-90",
          )}
        >
          ▶
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-medium">{triggerLabel(run.trigger)}</span>
            <RunStatusPill status={run.status} />
            {escalated && run.status === "completed" && (
              <span className="text-[13px] text-muted-foreground">· you were asked</span>
            )}
          </div>

          {blurb && (
            <p className={cx("mt-1 text-[14px] leading-normal text-muted-foreground", !open && "line-clamp-2")}>
              {blurb}
            </p>
          )}
          {run.error && !run.summary && (
            <p className="mt-1 text-[14px] text-deny-text">{run.error}</p>
          )}

          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground">
            <span className="tnum">
              {run.action_count} {run.action_count === 1 ? "step" : "steps"}
            </span>
            {run.duration_ms > 0 && <span className="tnum">{duration(run.duration_ms)}</span>}
            <span>{ago(run.started_at)}</span>
            <span className="ident">{run.run_id}</span>
          </div>
        </div>
      </button>

      {open && (
        <ol className="reveal border-t bg-background/60 px-5 py-2">
          {actions.length === 0 && (
            <li className="py-2 text-[14px] text-muted-foreground">
              No steps recorded — the run failed before it called anything.
            </li>
          )}
          {actions.map((action) => {
            const detail = describeAction(action, currency);
            return (
              <li key={action.action_id} className="flex gap-3 border-b py-2.5 last:border-b-0">
                <ActionStatusMark status={action.status} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span className="ident text-[13px] font-medium text-foreground">
                      {humanTool(action.tool)}
                    </span>
                    <RiskPill risk={action.risk_level} />
                    {action.latency_ms > 0 && (
                      <span className="tnum text-[12px] text-muted-foreground/70">
                        {duration(action.latency_ms)}
                      </span>
                    )}
                  </div>
                  {detail && <p className="mt-0.5 text-[14px] leading-snug">{detail}</p>}
                  <PolicyNote decision={action.policy_decision} reason={action.policy_reason} />
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
