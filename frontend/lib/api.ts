import type {
  Approval,
  BusinessConfig,
  Conversation,
  Dashboard,
  AgentRun,
  Task,
  Booking,
} from "./types";

const BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8010").replace(/\/$/, "");
const TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (init?.body) headers["content-type"] = "application/json";
  if (TOKEN) headers.authorization = `Bearer ${TOKEN}`;

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    // A dead backend is the most likely failure in a demo, so name it plainly
    // rather than surfacing "Failed to fetch".
    throw new ApiError(`Cannot reach the API at ${BASE}. Is \`make api\` running?`, 0);
  }

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json())?.detail;
    } catch {
      detail = await response.text().catch(() => undefined);
    }
    throw new ApiError(
      typeof detail === "string" ? detail : `${response.status} on ${path}`,
      response.status,
      detail,
    );
  }

  return response.json() as Promise<T>;
}

export const api = {
  dashboard: () => request<Dashboard>("/api/dashboard"),

  business: () => request<BusinessConfig>("/api/business"),

  approvals: (status: string | null = "pending") =>
    request<{ count: number; approvals: Approval[] }>(
      `/api/approvals${status ? `?status=${status}` : "?status="}`,
    ),

  runs: (limit = 30) => request<{ count: number; runs: AgentRun[] }>(`/api/runs?limit=${limit}`),

  run: (runId: string) => request<AgentRun>(`/api/runs/${runId}`),

  tasks: () => request<{ count: number; overdue: number; tasks: Task[] }>("/api/tasks"),

  bookings: (upcoming = true) =>
    request<{ count: number; bookings: Booking[] }>(`/api/bookings?upcoming=${upcoming}`),

  conversations: () =>
    request<{ count: number; conversations: Conversation[] }>("/api/conversations"),

  conversation: (id: string) => request<Conversation>(`/api/conversations/${id}`),

  /** Approve or reject, and resume the run that was waiting on it.
   *  `wait` blocks until the resumed run finishes — useful for a demo, slow for a UI. */
  decide: (approvalId: string, approved: boolean, note?: string, wait = false) =>
    request<{ approval: Approval; run_id: string; status: string }>(
      `/api/approvals/${approvalId}/decide?wait=${wait}`,
      {
        method: "POST",
        body: JSON.stringify({ approved, note: note || null, decided_by: "owner" }),
      },
    ),

  /** Hand the agent an inbound customer message. */
  sendMessage: (body: {
    body: string;
    conversation_id?: string;
    customer_name?: string;
    customer_email?: string;
  }) =>
    request<{ accepted: boolean; conversation_id: string; run_id?: string; status: string }>(
      "/api/messages?wait=false",
      { method: "POST", body: JSON.stringify(body) },
    ),

  /** Fire the scheduled follow-up sweep by hand. */
  sweepFollowUps: () =>
    request<{ due: number }>("/api/sweeps/follow-ups?wait=false", { method: "POST" }),

  updatePolicy: (policyType: string, rules: Record<string, number>) =>
    request<{ ok: boolean; policy_type: string; rules: Record<string, number>; rejected: string[] }>(
      `/api/business/policies/${policyType}`,
      { method: "PUT", body: JSON.stringify({ rules }) },
    ),
};

export { BASE as API_BASE };
