"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { money } from "@/lib/format";
import type { BusinessConfig } from "@/lib/types";

import { Pill } from "./status";
import { Button, Card, SectionHeader } from "./ui";

export type Unit = "money" | "percent" | "hours" | "days" | "count";

export interface FieldSpec {
  key: string;
  label: string;
  unit: Unit;
  help: string;
}

export interface PolicySpec {
  type: string;
  title: string;
  lede: string;
  fields: FieldSpec[];
}

function suffix(unit: Unit): string {
  switch (unit) {
    case "percent":
      return "%";
    case "hours":
      return "hours";
    case "days":
      return "days";
    case "count":
      return "times";
    default:
      return "";
  }
}

/** One policy, editable.
 *
 *  Saving writes the row the risk engine reads, so the effect is immediate and total:
 *  the agent's authority changes on its next tool call, with no redeploy and no prompt
 *  edit. That is the claim, so the UI says it plainly after a save rather than showing
 *  a generic toast.
 */
export function PolicyEditor({
  spec,
  business,
  onSaved,
}: {
  spec: PolicySpec;
  business: BusinessConfig;
  onSaved?: () => void;
}) {
  const stored = business.policies[spec.type]?.rules ?? {};
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-seed when the server value changes, but never while the owner is mid-edit.
  useEffect(() => {
    setDraft(
      Object.fromEntries(spec.fields.map((field) => [field.key, String(stored[field.key] ?? "")])),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(stored)]);

  const dirty = spec.fields.some(
    (field) => draft[field.key] !== undefined && draft[field.key] !== String(stored[field.key] ?? ""),
  );

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const rules: Record<string, number> = {};
      for (const field of spec.fields) {
        const raw = draft[field.key];
        if (raw === undefined || raw === "") continue;
        const value = Number(raw);
        if (Number.isNaN(value) || value < 0) {
          throw new Error(`${field.label} must be a number that is not negative.`);
        }
        rules[field.key] = value;
      }
      await api.updatePolicy(spec.type, rules);
      setSaved(true);
      onSaved?.();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <SectionHeader
        title={spec.title}
        hint={business.policies[spec.type]?.source === "default" ? "platform default" : undefined}
      />
      <div className="px-5 py-4">
        <p className="max-w-2xl text-[14px] text-muted-foreground">{spec.lede}</p>

        <div className="mt-4 space-y-3">
          {spec.fields.map((field) => (
            <div key={field.key} className="sm:flex sm:items-baseline sm:gap-4">
              <label
                htmlFor={`${spec.type}-${field.key}`}
                className="block text-[15px] sm:w-64 sm:shrink-0"
              >
                {field.label}
                <span className="mt-0.5 block text-[13px] text-muted-foreground">{field.help}</span>
              </label>
              <div className="mt-1 flex items-center gap-2 sm:mt-0">
                {field.unit === "money" && (
                  <span className="text-[14px] text-muted-foreground">{business.currency}</span>
                )}
                <input
                  id={`${spec.type}-${field.key}`}
                  type="number"
                  inputMode="decimal"
                  min={0}
                  value={draft[field.key] ?? ""}
                  onChange={(event) => {
                    setSaved(false);
                    setDraft({ ...draft, [field.key]: event.target.value });
                  }}
                  className="tnum w-32 rounded-md border border-[--color-border-strong] bg-background px-2.5 py-1.5 text-[15px]"
                />
                {suffix(field.unit) && (
                  <span className="text-[14px] text-muted-foreground">{suffix(field.unit)}</span>
                )}
              </div>
            </div>
          ))}
        </div>

        <PolicySentence type={spec.type} rules={stored} currency={business.currency} />

        {error && (
          <p className="mt-3 rounded-md border border-deny-border bg-deny-surface px-3 py-2 text-[14px] text-deny-text">
            {error}
          </p>
        )}

        <div className="mt-4 flex items-center gap-3">
          <Button tone="primary" onClick={() => void save()} disabled={saving || !dirty}>
            {saving ? "Saving…" : "Save"}
          </Button>
          {saved && !dirty && (
            <Pill tone="ok" glyph="✓">
              In force from the agent&rsquo;s next step
            </Pill>
          )}
        </div>
      </div>
    </Card>
  );
}

/** Restate the numbers as a sentence, because a column of inputs does not tell an
 *  owner what they have actually agreed to. */
function PolicySentence({
  type,
  rules,
  currency,
}: {
  type: string;
  rules: Record<string, number>;
  currency: string;
}) {
  const n = (key: string) => rules[key];
  let text: string | null = null;

  if (type === "refund" && n("auto_approve_below") !== undefined) {
    text =
      `Right now the agent can refund up to ${money(n("auto_approve_below"), currency)} by itself. ` +
      `Between that and ${money(n("approval_required_below"), currency)} it stops and asks you. ` +
      `Anything larger it refuses and puts on your list. Claims older than ${n("window_days")} days are refused.`;
  } else if (type === "discount" && n("auto_approve_percent") !== undefined) {
    text =
      `Up to ${n("auto_approve_percent")}% is the agent's call. ` +
      `Up to ${n("approval_required_percent")}% is yours. Beyond that it will not propose one.`;
  } else if (type === "cancellation" && n("free_cancellation_hours") !== undefined) {
    text =
      `With ${n("free_cancellation_hours")} hours' notice the agent cancels free of charge. ` +
      `Inside that, a ${n("late_cancellation_fee_percent")}% fee is at stake, so it asks you first.`;
  } else if (type === "rescheduling" && n("free_reschedules") !== undefined) {
    text =
      `The agent will move a booking ${n("free_reschedules")} times without asking, ` +
      `provided there are at least ${n("min_notice_hours")} hours' notice.`;
  }

  if (!text) return null;
  return (
    <p className="mt-4 border-l-2 border-primary/40 bg-accent/40 px-3 py-2 text-[14px] leading-normal">
      {text}
    </p>
  );
}
