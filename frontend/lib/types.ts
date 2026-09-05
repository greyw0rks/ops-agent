/** Shapes returned by the backend. Kept hand-written and narrow: these mirror the
 *  service-layer dicts in `backend/app/services`, so a drift shows up as a type
 *  error rather than as an undefined at runtime. */

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";

export type ActionStatus = "success" | "error" | "blocked" | "awaiting_approval";

export type PolicyDecision = "allow" | "require_approval" | "deny";

export type RunStatus = "running" | "awaiting_approval" | "completed" | "failed";

export interface AgentAction {
  action_id: string;
  sequence: number;
  tool: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  status: ActionStatus;
  risk_level: RiskLevel;
  policy_decision: PolicyDecision;
  policy_reason: string | null;
  approval_id: string | null;
  latency_ms: number;
  at: string | null;
}

export interface AgentRun {
  run_id: string;
  trigger: string;
  trigger_ref: string | null;
  intent: string | null;
  status: RunStatus;
  summary: string | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number;
  action_count: number;
  tokens: { input: number; output: number };
  actions?: AgentAction[];
}

export interface EvidenceItem {
  type: string;
  id: string;
  label: string;
}

export interface Approval {
  approval_id: string;
  run_id: string;
  action_type: string;
  risk_level: RiskLevel;
  title: string;
  reason: string;
  recommended_action: string;
  policy_basis: string | null;
  amount: number | null;
  currency: string | null;
  evidence: EvidenceItem[];
  payload: Record<string, unknown>;
  status: "pending" | "approved" | "rejected" | "expired";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  requested_at: string | null;
}

export interface Booking {
  booking_id: string;
  reference: string;
  customer_id: string;
  service_id: string;
  service_name: string | null;
  starts_at: string | null;
  ends_at: string | null;
  status: string;
  price: number;
  notes: string | null;
  created_by: string;
}

export interface Task {
  task_id: string;
  title: string;
  description: string | null;
  priority: "low" | "normal" | "high" | "urgent";
  status: string;
  due_at: string | null;
  booking_id: string | null;
  customer_id: string | null;
  created_by: string;
}

export interface Refund {
  refund_id: string;
  booking_id: string;
  customer_id: string;
  amount: number;
  status: string;
  reason: string | null;
  approval_id: string | null;
  created_at: string | null;
}

export interface DashboardStats {
  runs: number;
  completed: number;
  handled_without_you: number;
  awaiting_you: number;
  tool_calls: number;
  bookings_upcoming: number;
  open_tasks: number;
  overdue_tasks: number;
}

export interface Dashboard {
  business: { name: string; currency: string; timezone: string };
  needs_you: Approval[];
  activity: AgentRun[];
  upcoming_bookings: Booking[];
  open_tasks: Task[];
  recent_refunds: Refund[];
  stats: DashboardStats;
}

export interface PolicyBundle {
  policy_type: string;
  found: boolean;
  source?: string;
  rules: Record<string, number>;
  summary?: string | null;
}

export interface BusinessConfig {
  business_id: string;
  name: string;
  industry: string;
  currency: string;
  timezone: string;
  contact_email: string | null;
  contact_phone: string | null;
  opening_hours: Record<string, [string, string]>;
  concurrent_capacity: number;
  slot_interval_minutes: number;
  catalog: {
    service_id: string;
    name: string;
    description: string | null;
    base_price: number;
    duration_minutes: number;
    price_modifiers: Record<string, number>;
  }[];
  policies: Record<string, PolicyBundle>;
  agent: {
    provider: string;
    model_id: string;
    region: string | null;
    max_tokens: number;
  };
}

export interface ConversationMessage {
  message_id: string;
  direction: "inbound" | "outbound";
  author: string;
  body: string;
  sent_at: string | null;
}

export interface Conversation {
  conversation_id: string;
  customer_id: string | null;
  subject: string | null;
  channel: string;
  status: string;
  last_message_at: string | null;
  follow_up_due_at: string | null;
  message_count?: number;
  customer?: { customer_id: string; name: string; email: string | null } | null;
  messages?: ConversationMessage[];
}
