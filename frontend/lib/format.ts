/** Formatting helpers.
 *
 *  The backend already renders every timestamp in the business's own timezone and
 *  returns it as a local ISO string, so nothing here converts zones — doing that
 *  again in the browser is how a booking ends up an hour out.
 */

export function money(amount: number | null | undefined, currency = "NGN"): string {
  if (amount === null || amount === undefined) return "—";
  return `${currency} ${amount.toLocaleString("en-NG", {
    minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  })}`;
}

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "Sat 12 Sep, 1:00 PM" — the four things a customer or owner actually needs. */
export function dayTime(iso: string | null | undefined): string {
  const date = parse(iso);
  if (!date) return "—";
  return date.toLocaleString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

export function timeOnly(iso: string | null | undefined): string {
  const date = parse(iso);
  if (!date) return "—";
  return date.toLocaleString("en-GB", { hour: "numeric", minute: "2-digit", hour12: true });
}

/** "4 minutes ago", "yesterday" — for a feed the owner skims. */
export function ago(iso: string | null | undefined): string {
  const date = parse(iso);
  if (!date) return "—";
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return dayTime(iso);
}

export function duration(ms: number | null | undefined): string {
  if (!ms) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** `issue_refund` → `issue refund`. Tool names are the agent's vocabulary, not the
 *  owner's, so they are shown as identifiers but read as words. */
export function humanTool(tool: string): string {
  return tool.replace(/_/g, " ");
}

export function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, " ");
}

/** The event that woke the agent, in the owner's language. */
const TRIGGERS: Record<string, string> = {
  CustomerMessageReceived: "Customer message",
  FollowUpDue: "Follow-up due",
  DocumentReceived: "Document received",
  TaskDue: "Task due",
  DailySummaryDue: "Daily summary",
  ApprovalResolved: "Your decision",
};

export function triggerLabel(trigger: string): string {
  return TRIGGERS[trigger] ?? titleCase(trigger);
}
