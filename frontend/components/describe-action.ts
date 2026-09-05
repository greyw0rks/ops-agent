import { dayTime, money } from "@/lib/format";
import type { AgentAction } from "@/lib/types";

/** Turn a tool call's arguments and result into the one line an owner would want.
 *
 *  The raw JSON is available and is what the audit trail stores, but a feed of
 *  pretty-printed objects is unreadable. Each tool gets the fields that make its call
 *  meaningful — "BH-1045 · Sat 12 Sep, 1:00 PM · NGN 10,500" rather than eleven keys.
 */
export function describeAction(action: AgentAction, currency = "NGN"): string | null {
  const out = action.output ?? {};
  const arg = action.input ?? {};

  const str = (value: unknown): string | null =>
    typeof value === "string" && value.trim() ? value : null;
  const num = (value: unknown): number | null => (typeof value === "number" ? value : null);

  switch (action.tool) {
    case "find_customer": {
      const name = str(out.name);
      if (name) return `${name}${out.matched_on ? ` · matched on ${out.matched_on}` : ""}`;
      return out.found === false ? `no match${out.reason ? ` · ${out.reason}` : ""}` : null;
    }
    case "get_customer_history": {
      const bits: string[] = [];
      const name = str(out.name);
      if (name) bits.push(name);
      const bookings = num(out.booking_count);
      if (bookings !== null) bits.push(`${bookings} booking${bookings === 1 ? "" : "s"}`);
      const refunded = num(out.total_refunded);
      if (refunded) bits.push(`${money(refunded, currency)} refunded before`);
      return bits.join(" · ") || null;
    }
    case "get_service_catalog": {
      const services = Array.isArray(out.services) ? out.services.length : null;
      return services === null ? null : `${services} services`;
    }
    case "get_business_policy":
      return str(arg.policy_type) ? `read the ${String(arg.policy_type)} policy` : null;
    case "calculate_price": {
      const price = num(out.price);
      if (price === null) return null;
      const lines = Array.isArray(out.breakdown) ? out.breakdown.length : 0;
      return `${money(price, currency)}${lines > 1 ? ` · ${lines} line items` : ""}`;
    }
    case "check_availability": {
      const slots = Array.isArray(out.slots) ? out.slots.length : null;
      const day = str(arg.date) ?? str(out.date);
      if (out.available === false) return `${day ?? "that day"} · ${str(out.reason) ?? "nothing free"}`;
      return slots === null ? null : `${day ?? ""} · ${slots} slot${slots === 1 ? "" : "s"} free`.trim();
    }
    case "create_booking":
    case "reschedule_booking":
    case "cancel_booking":
    case "get_booking": {
      const starts = str(out.starts_at);
      const bits = [
        str(out.reference),
        starts ? dayTime(starts) : null,
        num(out.price) !== null ? money(num(out.price), currency) : null,
      ];
      const fee = num(out.cancellation_fee);
      if (fee) bits.push(`${money(fee, currency)} fee`);
      return bits.filter(Boolean).join(" · ") || null;
    }
    case "issue_refund": {
      const amount = num(out.amount) ?? num(arg.amount);
      if (amount === null) return null;
      const authorised = str(out.authorised_by_approval);
      return `${money(amount, currency)}${authorised ? ` · authorised by ${authorised}` : ""}`;
    }
    case "apply_discount": {
      const percent = num(out.percent) ?? num(arg.percent);
      const now = num(out.new_price);
      return percent === null ? null : `${percent}%${now !== null ? ` · now ${money(now, currency)}` : ""}`;
    }
    case "send_message": {
      if (out.sent === false) return str(out.reason) ?? "not sent";
      return str(out.preview) ?? "reply sent";
    }
    case "create_task":
      return str(out.title) ?? str(arg.title);
    case "update_customer": {
      const updated = Array.isArray(out.updated) ? (out.updated as string[]) : [];
      return updated.length ? `updated ${updated.join(", ")}` : null;
    }
    case "resolve_conversation":
      return "thread closed";
    case "record_supplier_invoice": {
      if (out.error === "duplicate_invoice") return "duplicate — already on file";
      const amount = num(out.amount);
      return [str(out.supplier_name), amount !== null ? money(amount, currency) : null]
        .filter(Boolean)
        .join(" · ") || null;
    }
    default: {
      if (typeof out.error === "string") return out.error;
      const scalars = Object.entries(out)
        .filter(([, v]) => typeof v === "string" || typeof v === "number")
        .slice(0, 2)
        .map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`);
      return scalars.join(" · ") || null;
    }
  }
}
