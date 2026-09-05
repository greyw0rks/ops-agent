"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { ago, money, titleCase } from "@/lib/format";
import type { Approval } from "@/lib/types";

import { Pill } from "./status";
import { Card, cx } from "./ui";

/** One decision the agent handed back.
 *
 *  Read top to bottom: what it wants to do, how much, why, which rule sent it here,
 *  what it looked at. Then the two buttons.
 *
 *  Approve and Reject are deliberately the same shape, size and weight. A filled
 *  primary "Approve" next to a ghost "Reject" is a nudge, and this is the one screen
 *  in the product where the interface must not have an opinion. The brand blue is
 *  reserved for navigation and never appears on a consequential action.
 */
export function DecisionCard({
  approval,
  onDecided,
}: {
  approval: Approval;
  onDecided?: () => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<"approved" | "rejected" | null>(null);

  async function decide(approved: boolean) {
    setBusy(approved ? "approve" : "reject");
    setError(null);
    try {
      await api.decide(approval.approval_id, approved, note.trim() || undefined);
      setDone(approved ? "approved" : "rejected");
      onDecided?.();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  }

  const amount =
    approval.amount !== null ? money(approval.amount, approval.currency ?? "NGN") : null;
  // The policy engine usually builds the amount into the title ("Refund NGN 7,500.00 —
  // BH-1041"), so repeating it underneath is noise. Show it only when it is missing.
  const showAmount = amount !== null && !approval.title.includes(approval.currency ?? "NGN");

  if (done) {
    return (
      <Card className="reveal px-5 py-4">        <div className="flex flex-wrap items-center gap-2 text-[15px]">
          <Pill tone={done === "approved" ? "ok" : "deny"} glyph={done === "approved" ? "✓" : "⊘"}>
            {titleCase(done)}
          </Pill>
          <span className="font-medium">{approval.title}</span>
        </div>
        <p className="mt-1.5 text-[14px] text-muted-foreground">
          The agent has picked the run back up from where it paused
          {note.trim() ? " and has your note." : "."}
        </p>
      </Card>
    );
  }

  return (
    <Card as="article" className="reveal overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-wait-border bg-wait-surface px-5 py-2.5">
        <Pill tone="wait" glyph="!" className="border-wait-text/25">
          Needs your decision
        </Pill>
        <span className="ident text-wait-text/80">{approval.action_type}</span>
        <span className="ml-auto text-[13px] text-wait-text/80">{ago(approval.requested_at)}</span>
      </div>

      <div className="px-5 py-4">
        <h3 className="text-[19px] font-semibold leading-snug tracking-tight">{approval.title}</h3>

        {showAmount && (
          <p className="tnum mt-1 text-[15px] text-muted-foreground">{amount}</p>
        )}

        <dl className="mt-4 space-y-2.5">
          <div>
            <dt className="text-[13px] font-medium uppercase tracking-wide text-muted-foreground">
              What it wants to do
            </dt>
            <dd className="mt-0.5 text-[16px] leading-relaxed">{approval.recommended_action}</dd>
          </div>
          <div>
            <dt className="text-[13px] font-medium uppercase tracking-wide text-muted-foreground">
              Why it is asking
            </dt>
            <dd className="mt-0.5 text-[16px] leading-relaxed">{approval.reason}</dd>
          </div>
          {approval.policy_basis && (
            <div>
              <dt className="text-[13px] font-medium uppercase tracking-wide text-muted-foreground">
                Your rule that sent it here
              </dt>
              <dd className="ident mt-0.5 break-words text-foreground">{approval.policy_basis}</dd>
            </div>
          )}
        </dl>

        {approval.evidence.length > 0 && (
          <div className="mt-4 border-t pt-3">
            <p className="text-[13px] font-medium uppercase tracking-wide text-muted-foreground">
              What it looked at
            </p>
            <ul className="mt-1.5 flex flex-wrap gap-1.5">
              {approval.evidence.map((item) => (
                <li
                  key={`${item.type}-${item.id}`}
                  className="flex items-baseline gap-1.5 rounded-sm border bg-background px-2 py-0.5 text-[13px]"
                >
                  {item.label}
                  <span className="ident text-muted-foreground">{item.id}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-4 border-t pt-4">
          <label
            htmlFor={`note-${approval.approval_id}`}
            className="block text-[14px] font-medium"
          >
            Anything to add?
          </label>
          <p className="mt-0.5 text-[13px] text-muted-foreground">
            Optional — but the agent reads it and acts on it, so &ldquo;also offer her a free
            oven clean&rdquo; is enough.
          </p>
          <textarea
            id={`note-${approval.approval_id}`}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={2}
            placeholder="Agreed."
            className="mt-2 w-full resize-y rounded-md border border-[--color-border-strong] bg-background px-3 py-2 text-[16px] placeholder:text-muted-foreground/70"
          />
        </div>

        {error && (
          <p className="mt-3 rounded-md border border-deny-border bg-deny-surface px-3 py-2 text-[14px] text-deny-text">
            {error}
          </p>
        )}

        <div className="mt-4 grid grid-cols-2 gap-3">
          <DecisionButton
            tone="deny"
            glyph="⊘"
            label="Reject"
            busyLabel="Rejecting…"
            busy={busy === "reject"}
            disabled={busy !== null}
            onClick={() => decide(false)}
          />
          <DecisionButton
            tone="ok"
            glyph="✓"
            label="Approve"
            busyLabel="Approving…"
            busy={busy === "approve"}
            disabled={busy !== null}
            onClick={() => decide(true)}
          />
        </div>
      </div>
    </Card>
  );
}

function DecisionButton({
  tone,
  glyph,
  label,
  busyLabel,
  busy,
  disabled,
  onClick,
}: {
  tone: "ok" | "deny";
  glyph: string;
  label: string;
  busyLabel: string;
  busy: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  const tones = {
    ok: "border-ok-border bg-ok-surface text-ok-text hover:border-ok-text/40",
    deny: "border-deny-border bg-deny-surface text-deny-text hover:border-deny-text/40",
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cx(
        "flex items-center justify-center gap-2 rounded-md border px-4 py-2.5 text-[15px] font-semibold transition-colors duration-150",
        tones[tone],
      )}
    >
      <span aria-hidden>{glyph}</span>
      {busy ? busyLabel : label}
    </button>
  );
}
