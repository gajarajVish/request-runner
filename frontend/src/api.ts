import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T,>(path: string) => fetch(path, { credentials: "same-origin" }).then((r) => handle<T>(r)),
  send: <T,>(method: string, path: string, body?: unknown) =>
    fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? {} : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then((r) => handle<T>(r)),
  post: <T,>(path: string, body?: unknown) => api.send<T>("POST", path, body ?? {}),
  put: <T,>(path: string, body?: unknown) => api.send<T>("PUT", path, body),
  patch: <T,>(path: string, body?: unknown) => api.send<T>("PATCH", path, body),
  form: <T,>(path: string, form: FormData) =>
    fetch(path, { method: "POST", credentials: "same-origin", body: form }).then((r) => handle<T>(r)),
};

// --------------------------------------------------------------------------- types

export type Me = {
  user: { id: number; name: string; email: string } | null;
  dev: boolean;
  app_name: string;
  now: string;
  inbound_domain: string;
  email_provider: string;
  llm_provider: string;
};

export type Flag = { code: string; message: string; blocking?: boolean; [k: string]: unknown };

export type Owner = { provider_id: number; email: string; name: string | null; closed_at: string | null };

export type RequestSummary = {
  id: number;
  title: string;
  label: string;
  external_id: string | null;
  state: string;
  state_label: string;
  origin: string;
  due_date: string | null;
  overdue_days: number;
  owners: Owner[];
  met: number;
  total: number;
  auto_contact_count: number;
  flags: Flag[];
  updated_at: string;
  created_at: string;
  import_list_id: number | null;
};

export type Citation = {
  evidence_id: string | null;
  file_id: number | null;
  filename: string | null;
  location: string;
  quote: string | null;
  visual: boolean;
  verified: boolean;
  problem: string | null;
  note: string | null;
};

export type Subpoint = { key: string; text: string; condition?: string | null };

export type Verdict = {
  verdict: "met" | "partly_met" | "not_met" | "unreadable" | "pending";
  source: string;
  rationale: string;
  missing: string[];
  citations: Citation[];
  subpoints: { key: string; status?: string; verdict?: string; citations?: Citation[]; note?: string; text?: string }[];
  review_flags: string[];
  model_verdict?: string;
  override_reason?: string;
};

export type Item = {
  key: string;
  kind: "document" | "answer";
  description: string;
  criteria: Record<string, unknown>;
  subpoints: Subpoint[];
  verdict?: Verdict;
};

export type Version = {
  id: number;
  number: number;
  status: string;
  provider_email: string | null;
  provider_name: string | null;
  due_date: string | null;
  notes: string[];
  created_by: string;
  created_at: string;
  confirmed_at: string | null;
  items: Item[];
};

export type Comment = { id: number; author: string; kind: string; body: string; payload: Record<string, any>; created_at: string };

export type EvidenceFile = {
  id: number;
  filename: string;
  kind: string;
  source: string;
  status: string;
  reason: string | null;
  accepted: boolean;
  detected_type: string | null;
  size: number;
  flags: { code: string; location?: string; quote?: string }[];
  created_at: string;
  parent_file_id: number | null;
  inbound_id: number | null;
  assigned: string | null;
  text: string | null;
  images: { index: number; label: string; why?: string }[];
  pages: number | null;
};

export type Outbound = {
  id: number;
  kind: string;
  status: string;
  from: string;
  reply_to: string | null;
  to: string[];
  cc: string[];
  subject: string;
  text: string;
  message_id: string;
  in_reply_to: string | null;
  references: string | null;
  created_at: string;
  sent_at: string | null;
  last_error: string | null;
  request_ids: number[];
  counted_request_ids: number[];
  attempts: number;
};

export type Inbound = {
  id: number;
  from: string | null;
  from_name: string | null;
  to: string[];
  subject: string | null;
  message_id: string | null;
  in_reply_to: string | null;
  received_at: string;
  status: string;
  match_method: string | null;
  match_notes: string[];
  suggested_conversation_ids: number[];
  is_auto_reply: boolean;
  sender_is_owner: boolean | null;
  text: string;
  classification: Record<string, unknown> | null;
  error: string | null;
  suggestions?: { conversation_id: number; subject: string; provider: string }[];
};

export type AuditEntry = { id: number; at: string; actor: string; actor_detail: string | null; action: string; detail: Record<string, unknown>; request_id?: number | null };

export type RequestDetail = RequestSummary & {
  aliases: string[];
  instructions: string | null;
  backup_email: string | null;
  ownership_mode: "any" | "all";
  cc_requester: boolean;
  max_auto_contacts: number;
  handback_reason: string | null;
  handed_back_at: string | null;
  reminder_sent_at: string | null;
  overdue_sent_at: string | null;
  escalated_at: string | null;
  dependencies: { id: number; label: string; state: string }[];
  current_version: Version | null;
  proposed_version: Version | null;
  versions: { id: number; number: number; status: string; created_at: string; confirmed_at: string | null }[];
  comments: Comment[];
  files: EvidenceFile[];
  messages: Outbound[];
  inbound: Inbound[];
  conversations: { id: number; reply_to: string; subject: string }[];
  questions: { id: number; question: string; status: string; answer: string | null; created_at: string; delivered_at: string | null }[];
  checks: { id: number; status: string; trigger: string; error: string | null; suspicious: { evidence_id: string; location: string; quote: string; reason: string }[]; created_at: string; finished_at: string | null }[];
  audit: AuditEntry[];
};

export type ImportRowView = {
  id: number;
  position: number;
  external_id: string;
  action: "new" | "unchanged" | "changed" | "duplicate" | "error" | "removed";
  merged_into: string | null;
  title: string;
  instructions: string;
  due_date: string | null;
  owners: { email: string; name: string | null }[];
  backup_email: string | null;
  depends_on: string[];
  edits: Record<string, unknown>;
  changes: { field: string; old: unknown; new: unknown }[];
  flags: Flag[];
  scope: { title?: string; vague?: boolean; vague_reason?: string | null; items?: Omit<Item, "key" | "verdict">[]; assumptions?: string[]; cached?: boolean; edited?: boolean };
  ownership_mode: "any" | "all";
  request_id: number | null;
  include: boolean;
  blocked: boolean;
};

export type ImportBatch = {
  id: number;
  list: { id: number; name: string } | null;
  filename: string;
  status: "analyzing" | "review" | "applied" | "error" | "discarded";
  errors: string[];
  created_at: string;
  applied_at: string | null;
  summary: Record<string, number>;
  rows: ImportRowView[];
  drafts: Outbound[];
};

export type ImportListSummary = {
  id: number;
  name: string;
  batches: { id: number; filename: string; status: string; created_at: string; applied_at: string | null; summary: Record<string, number> }[];
};

export type Dashboard = {
  today: string;
  counts: Record<string, number>;
  providers_behind: number;
  providers: { provider: { id: number; email: string; name: string | null }; open: number; overdue: number; max_days_overdue: number; items: RequestSummary[] }[];
  all_providers: string[];
};

export type HubView = {
  provider: { name: string | null; email: string };
  app_name: string;
  items: {
    request_id: number;
    label: string;
    title: string;
    requester: string;
    due_date: string | null;
    overdue_days: number;
    shared: boolean;
    checklist: { key: string; kind: string; description: string; subpoints: string[]; status: "received" | "outstanding"; missing: string[] }[];
    submitted: { id: number; filename: string; kind: string; at: string; status: string }[];
  }[];
};

// --------------------------------------------------------------------------- live updates

/** Subscribe to the server's change feed; invalidate cached queries when something changes. */
export function useLiveUpdates(enabled: boolean) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!enabled) return;
    const es = new EventSource("/api/events", { withCredentials: true });
    let timer: number | undefined;
    const touched = new Set<string>();
    es.onmessage = (ev) => {
      try {
        const batch = JSON.parse(ev.data) as { topic: string; request_id: number | null }[];
        for (const e of batch) {
          if (e.request_id) touched.add(`request:${e.request_id}`);
          touched.add(e.topic);
        }
      } catch {
        return;
      }
      // coalesce bursts (a check writes many events) into one refetch
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        for (const t of touched) {
          if (t.startsWith("request:")) qc.invalidateQueries({ queryKey: ["request", Number(t.slice(8))] });
        }
        qc.invalidateQueries({ queryKey: ["requests"] });
        qc.invalidateQueries({ queryKey: ["dashboard"] });
        qc.invalidateQueries({ queryKey: ["inbound"] });
        qc.invalidateQueries({ queryKey: ["audit"] });
        if (touched.has("import")) {
          qc.invalidateQueries({ queryKey: ["imports"] });
          qc.invalidateQueries({ queryKey: ["batch"] });
        }
        qc.invalidateQueries({ queryKey: ["me"] });
        touched.clear();
      }, 250);
    };
    return () => {
      window.clearTimeout(timer);
      es.close();
    };
  }, [enabled, qc]);
}

// --------------------------------------------------------------------------- formatting

export function fmtDate(s: string | null | undefined) {
  if (!s) return "";
  const d = new Date(s.length === 10 ? s + "T12:00:00" : s);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function fmtTime(s: string | null | undefined) {
  if (!s) return "";
  // server timestamps are naive UTC
  const d = new Date(s.endsWith("Z") || s.includes("+") ? s : s + "Z");
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function bytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
