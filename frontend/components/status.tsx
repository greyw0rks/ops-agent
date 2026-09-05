import type { ActionStatus, RiskLevel, RunStatus } from "@/lib/types";
import { cx } from "./ui";

/** Status is encoded twice, as a glyph and as a colour.
 *
 *  The palette engine reported the brand blue and the error red as
 *  "grayscale-fragile" — separable by hue but only 0.06 apart in lightness, so the
 *  distinction vanishes in grayscale, in print, and for some colour-vision
 *  deficiencies. A dashboard where "done" and "refused" can be confused is worse than
 *  useless, so nothing here depends on hue alone.
 */

type Tone = "ok" | "wait" | "deny" | "info" | "neutral";

const TONES: Record<Tone, string> = {
  ok: "border-ok-border bg-ok-surface text-ok-text",
  wait: "border-wait-border bg-wait-surface text-wait-text",
  deny: "border-deny-border bg-deny-surface text-deny-text",
  info: "border-info-border bg-info-surface text-info-text",
  neutral: "border-border bg-muted text-muted-foreground",
};

export function Pill({
  tone,
  glyph,
  children,
  className,
}: {
  tone: Tone;
  glyph?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-sm border px-1.5 py-px text-[12px] font-medium leading-5 whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {glyph && <span aria-hidden>{glyph}</span>}
      {children}
    </span>
  );
}

const ACTION: Record<ActionStatus, { tone: Tone; glyph: string; label: string }> = {
  success: { tone: "ok", glyph: "✓", label: "done" },
  awaiting_approval: { tone: "wait", glyph: "!", label: "paused for you" },
  blocked: { tone: "deny", glyph: "⊘", label: "refused" },
  error: { tone: "deny", glyph: "×", label: "failed" },
};

export function ActionStatusMark({ status }: { status: ActionStatus }) {
  const spec = ACTION[status] ?? ACTION.error;
  return (
    <span
      title={spec.label}
      aria-label={spec.label}
      className={cx(
        "inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-sm border text-[12px]",
        TONES[spec.tone],
      )}
    >
      <span aria-hidden>{spec.glyph}</span>
    </span>
  );
}

const RUN: Record<RunStatus, { tone: Tone; glyph: string; label: string }> = {
  completed: { tone: "ok", glyph: "✓", label: "Handled" },
  awaiting_approval: { tone: "wait", glyph: "!", label: "Waiting on you" },
  running: { tone: "info", glyph: "•", label: "Working" },
  failed: { tone: "deny", glyph: "×", label: "Failed" },
};

export function RunStatusPill({ status }: { status: RunStatus }) {
  const spec = RUN[status] ?? RUN.failed;
  return (
    <Pill tone={spec.tone} glyph={spec.glyph}>
      {spec.label}
    </Pill>
  );
}

/** Risk is the tool's declared level, not a judgement about this call. LOW is the
 *  overwhelming majority, so it is shown quietly and only MEDIUM and HIGH earn ink. */
export function RiskPill({ risk }: { risk: RiskLevel }) {
  if (risk === "LOW") {
    return <span className="ident text-muted-foreground/70">low risk</span>;
  }
  return (
    <Pill tone={risk === "HIGH" ? "deny" : "wait"} className="uppercase tracking-wide">
      {risk} risk
    </Pill>
  );
}

export function PolicyNote({
  decision,
  reason,
}: {
  decision: string;
  reason: string | null;
}) {
  if (decision === "allow" || !reason) return null;
  const tone: Tone = decision === "deny" ? "deny" : "wait";
  const label = decision === "deny" ? "Refused by policy" : "Sent to you by policy";
  return (
    <div
      className={cx(
        "mt-1.5 rounded-md border px-2.5 py-1.5 text-[13px] leading-snug",
        TONES[tone],
      )}
    >
      <span className="font-semibold">{label}. </span>
      {reason}
    </div>
  );
}
