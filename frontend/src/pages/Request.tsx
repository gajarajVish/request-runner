import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, bytes, fmtDate, fmtTime, type Comment, type EvidenceFile, type Item, type RequestDetail, type Version } from "../api";
import { ChecklistEditor, ChecklistView, emptyCriteria, toDraft, type DraftItem } from "../components/Checklist";
import { DraftEditor, InboundView, OutboundView } from "../components/Mail";
import { Badge, Button, Card, Disclosure, Empty, ErrorText, Field, FlagList, Icon, type IconName, Menu, Modal, RefId, Segmented, Spinner, StateBadge, VerdictBadge, cx, inputCls } from "../components/ui";

const OPEN_WITH_PROVIDER = new Set(["waiting_provider", "checking", "needs_more", "handed_back"]);
const TERMINAL = new Set(["complete", "closed_by_provider", "accepted", "cancelled"]);

export function RequestPage() {
  const id = Number(useParams().id);
  const q = useQuery({ queryKey: ["request", id], queryFn: () => api.get<RequestDetail>(`/api/requests/${id}`) });
  const [override, setOverride] = useState<Item | null>(null);

  if (q.isLoading) return null;
  if (q.error || !q.data) return <ErrorText error={q.error ?? "not found"} />;
  const r = q.data;
  const version = r.current_version ?? r.proposed_version;
  const files = r.files.filter((f) => !f.parent_file_id);

  return (
    <div>
      <Header r={r} />
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(380px,1fr)]">
        <div className="min-w-0 space-y-5">
          <Card
            title={r.current_version ? "Checklist" : "Proposed checklist"}
            actions={version && version.items.length > 0 && <span className="text-xs tabular-nums text-slate-500">{r.current_version ? `${r.met} of ${r.total} received` : `${version.items.length} item${version.items.length > 1 ? "s" : ""}`}</span>}
          >
            <LatestSuspicious r={r} />
            {version && version.items.length > 0 ? (
              <ChecklistView items={version.items} files={r.files} onOverride={r.current_version && OPEN_WITH_PROVIDER.has(r.state) ? setOverride : undefined} />
            ) : (
              <Empty icon="sparkle">{r.state === "scoping" ? "The agent is drafting a checklist…" : "No items yet. Use Edit in the conversation to add them."}</Empty>
            )}
            {r.current_version && r.proposed_version && (
              <p className="mt-3 rounded-md border border-brand-200 bg-brand-50 px-3 py-2 text-xs text-brand-900">A revised checklist is waiting for you to confirm in the conversation.</p>
            )}
          </Card>
          {files.length > 0 && (
            <Card title="Received files" actions={<span className="text-xs text-slate-500">{files.length}</span>}>
              <Files files={r.files} />
            </Card>
          )}
          <Questions r={r} />
        </div>
        <Thread r={r} />
      </div>
      <OverrideModal r={r} item={override} onClose={() => setOverride(null)} />
    </div>
  );
}

// --------------------------------------------------------------------------- header, next step & actions

function providerName(r: RequestDetail) {
  return r.owners.map((o) => o.name || o.email).join(r.ownership_mode === "all" ? " and " : " or ") || "the provider";
}

/** The one thing that happens next, in plain words. */
function NextStep({ r, onAct, busy }: { r: RequestDetail; onAct: (path: string) => void; busy: boolean }) {
  const who = providerName(r);
  const missing = r.total - r.met;
  const step: { tone: "brand" | "slate" | "amber" | "red" | "green"; title: string; body?: string; actions?: React.ReactNode } | null = (() => {
    switch (r.state) {
      case "scoping":
        return { tone: "slate", title: "Drafting a checklist", body: "The agent is turning your request into a checklist. This takes a few seconds." };
      case "waiting_requester":
        return { tone: "brand", title: "Your turn: confirm the checklist", body: "Check the proposed checklist in the conversation. Edit it if needed, then confirm. Nothing is sent yet." };
      case "ready_to_send":
        return { tone: "brand", title: "Your turn: approve the email", body: `Read the email to ${who} in the conversation, then approve it to send.` };
      case "waiting_provider":
        return { tone: "slate", title: `Waiting for ${who}`, body: "Nothing to do. Replies and uploads are checked automatically, and reminders go out before the due date." };
      case "checking":
        return { tone: "slate", title: `Checking what ${who} sent`, body: "Every file is compared against the checklist." };
      case "needs_more":
        return {
          tone: "amber",
          title: `${missing} of ${r.total} item${r.total > 1 ? "s" : ""} still missing`,
          body: `${who} has been told what is still needed. Follow-ups continue automatically (${r.auto_contact_count} of ${r.max_auto_contacts} used).`,
          actions: (
            <Button size="sm" onClick={() => onAct("manual-followup")} busy={busy}>
              <Icon name="send" /> Follow up now
            </Button>
          ),
        };
      case "handed_back":
        return {
          tone: "red",
          title: "Your decision: automatic follow-ups are used up",
          body: `${who} hasn't sent everything after ${r.max_auto_contacts} follow-ups. Keep waiting, follow up yourself, or accept what you have.`,
          actions: (
            <>
              <Button size="sm" variant="primary" onClick={() => onAct("resume")} busy={busy}>
                Keep waiting
              </Button>
              <Button size="sm" onClick={() => onAct("manual-followup")} busy={busy}>
                Follow up now
              </Button>
            </>
          ),
        };
      case "complete":
        return { tone: "green", title: "Complete", body: "Everything on the checklist was received and checked. The evidence for each item is below." };
      case "closed_by_provider":
        return { tone: "amber", title: `${who} said that's all they have`, body: missing ? `${missing} item${missing > 1 ? "s were" : " was"} not provided. What arrived is below.` : undefined };
      case "accepted":
        return { tone: "green", title: "Accepted", body: "You closed this with what was received." };
      case "cancelled":
        return { tone: "slate", title: "Cancelled" };
      default:
        return null;
    }
  })();
  if (!step) return null;
  const cls = { brand: "border-brand-200 bg-brand-50 text-brand-900", slate: "border-slate-200 bg-white text-slate-800", amber: "border-amber-200 bg-amber-50 text-amber-900", red: "border-red-200 bg-red-50 text-red-900", green: "border-emerald-200 bg-emerald-50 text-emerald-900" }[step.tone];
  return (
    <div className={cx("flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border px-4 py-3", cls)}>
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 text-[14px] font-semibold">
          {(r.state === "scoping" || r.state === "checking") && <Spinner />}
          {step.title}
        </p>
        {step.body && <p className="mt-0.5 text-[13px] opacity-90">{step.body}</p>}
      </div>
      {step.actions && <div className="flex gap-2">{step.actions}</div>}
    </div>
  );
}

function Header({ r }: { r: RequestDetail }) {
  const qc = useQueryClient();
  const [modal, setModal] = useState<null | "cancel" | "accept" | "due" | "email" | "audit">(null);
  const [reason, setReason] = useState("");
  const [due, setDue] = useState(r.due_date ?? "");
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api.post(`/api/requests/${r.id}/${path}`, body),
    onSuccess: () => {
      setModal(null);
      setReason("");
      qc.invalidateQueries({ queryKey: ["request", r.id] });
    },
  });
  const open = OPEN_WITH_PROVIDER.has(r.state);
  const emailCount = r.messages.filter((m) => m.status !== "draft").length + r.inbound.length;
  return (
    <div className="mb-5 space-y-4">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-xs text-slate-500">
        <Link to="/" className="hover:text-slate-800">
          Requests
        </Link>
        <Icon name="chevronRight" size={12} />
        <span className="text-slate-700">{r.external_id ?? `#${r.id}`}</span>
      </nav>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[20px] font-semibold tracking-tight text-slate-900">
            {r.external_id && <RefId className="text-[14px]">{r.external_id}</RefId>}
            {r.title}
            <StateBadge state={r.state} label={r.state_label} />
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-[13px] text-slate-600">
            {r.owners.length > 0 ? (
              <span>
                From <span className="font-medium text-slate-800">{providerName(r)}</span>
                {r.owners.length === 1 && r.owners[0]!.name && <span className="text-slate-500"> ({r.owners[0]!.email})</span>}
              </span>
            ) : (
              <span>No provider yet</span>
            )}
            {r.due_date && (
              <>
                <span aria-hidden>·</span>
                <span className={r.overdue_days ? "font-medium text-red-700" : ""}>
                  Due {fmtDate(r.due_date)}
                  {r.overdue_days > 0 && ` (${r.overdue_days} days overdue)`}
                </span>
              </>
            )}
            {r.backup_email && (
              <>
                <span aria-hidden>·</span>
                <span>Escalates to {r.backup_email}</span>
              </>
            )}
          </p>
        </div>
        <Menu
          items={[
            open && { label: "Re-check what was received", onClick: () => act.mutate({ path: "recheck" }) },
            open && r.state !== "needs_more" && r.state !== "handed_back" && { label: "Follow up now", hint: "Doesn't count toward the automatic limit", onClick: () => act.mutate({ path: "manual-followup" }) },
            { label: `Email history (${emailCount})`, onClick: () => setModal("email") },
            { label: "Audit log", onClick: () => setModal("audit") },
            open && { label: "Accept as is", hint: "Close with what was received", onClick: () => setModal("accept") },
            !TERMINAL.has(r.state) && { label: "Change due date", onClick: () => setModal("due") },
            !TERMINAL.has(r.state) && { label: "Cancel request", danger: true, onClick: () => setModal("cancel") },
          ]}
        />
      </div>
      <NextStep r={r} onAct={(path) => act.mutate({ path })} busy={act.isPending} />
      {r.dependencies.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          Depends on
          {r.dependencies.map((d) => (
            <Link key={d.id} to={`/requests/${d.id}`} className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 hover:border-slate-300">
              {d.label} <StateBadge state={d.state} />
            </Link>
          ))}
        </div>
      )}
      <FlagList flags={r.flags} />
      <ErrorText error={act.error} />
      <Modal open={modal === "email"} onClose={() => setModal(null)} title="Email history" wide>
        <Emails r={r} />
      </Modal>
      <Modal open={modal === "audit"} onClose={() => setModal(null)} title="Audit log" wide>
        <Audit r={r} />
      </Modal>
      <Modal open={modal === "cancel" || modal === "accept"} onClose={() => setModal(null)} title={modal === "cancel" ? "Cancel this request?" : "Accept what was received?"}>
        <div className="space-y-4">
          <p className="text-[13px] text-slate-700">{modal === "cancel" ? (open ? "The provider will be told they can stop working on it." : "Nothing has been sent yet.") : "The request closes as accepted. No more follow-ups are sent."}</p>
          <Field label="Reason (recorded in the audit log)">
            <input className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setModal(null)}>
              Keep request
            </Button>
            <Button variant={modal === "cancel" ? "danger" : "primary"} busy={act.isPending} onClick={() => act.mutate({ path: modal!, body: { reason } })}>
              {modal === "cancel" ? "Cancel request" : "Accept and close"}
            </Button>
          </div>
          <ErrorText error={act.error} />
        </div>
      </Modal>
      <Modal open={modal === "due"} onClose={() => setModal(null)} title="Change the due date">
        <div className="space-y-4">
          <Field label="New due date">
            <input type="date" className={inputCls} value={due} onChange={(e) => setDue(e.target.value)} />
          </Field>
          {open && <p className="text-xs text-slate-600">The provider gets one change notice. Reminders and overdue notices restart from the new date.</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setModal(null)}>
              Back
            </Button>
            <Button variant="primary" disabled={!due} busy={act.isPending} onClick={() => act.mutate({ path: "due-date", body: { due_date: due } })}>
              Save due date
            </Button>
          </div>
          <ErrorText error={act.error} />
        </div>
      </Modal>
    </div>
  );
}

function OverrideModal({ r, item, onClose }: { r: RequestDetail; item: Item | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [verdict, setVerdict] = useState("met");
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api.post(`/api/requests/${r.id}/override`, { item_key: item!.key, verdict, reason }),
    onSuccess: () => {
      setReason("");
      onClose();
      qc.invalidateQueries({ queryKey: ["request", r.id] });
    },
  });
  return (
    <Modal open={!!item} onClose={onClose} title="Override the verdict">
      {item && (
        <div className="space-y-3">
          <p className="text-sm text-slate-700">{item.description}</p>
          <p className="text-xs text-slate-500">
            Agent's verdict: <VerdictBadge verdict={item.verdict?.verdict ?? "pending"} />
          </p>
          <Field label="New verdict">
            <select className={inputCls} value={verdict} onChange={(e) => setVerdict(e.target.value)}>
              <option value="met">Met</option>
              <option value="partly_met">Partly met</option>
              <option value="not_met">Not met</option>
              <option value="unreadable">Unreadable</option>
            </select>
          </Field>
          <Field label="Reason (required, kept in the audit log)">
            <textarea className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <div className="flex justify-end">
            <Button variant="primary" disabled={!reason.trim()} busy={m.isPending} onClick={() => m.mutate()}>
              Save override
            </Button>
          </div>
          <ErrorText error={m.error} />
        </div>
      )}
    </Modal>
  );
}

// --------------------------------------------------------------------------- thread

function Thread({ r }: { r: RequestDetail }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"chat" | "change">("chat");
  const end = useRef<HTMLLIElement>(null);
  const sent = OPEN_WITH_PROVIDER.has(r.state);
  const post = useMutation({
    mutationFn: () => (sent && mode === "chat" ? api.post(`/api/requests/${r.id}/chat`, { text }) : api.post(`/api/requests/${r.id}/comments`, { text })),
    onSuccess: () => {
      setText("");
      qc.invalidateQueries({ queryKey: ["request", r.id] });
    },
  });
  const latestProposalId = useMemo(() => [...r.comments].reverse().find((c) => c.kind === "scope_proposal")?.id, [r.comments]);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [r.comments.length]);
  const placeholder = !sent
    ? TERMINAL.has(r.state)
      ? "Add a note"
      : "Reply to the agent: answer its questions or change the checklist"
    : mode === "chat"
      ? "Ask about this request, e.g. “What's still missing?” This doesn't change what's requested."
      : "Describe the change. You'll confirm a new checklist version before anything is sent.";

  return (
    <section className="flex flex-col rounded-md border border-slate-200 bg-white shadow-xs xl:sticky xl:top-6 xl:max-h-[calc(100vh-3rem)]">
      <header className="flex min-h-10 items-center justify-between border-b border-slate-200 px-4 py-2">
        <h2 className="text-[13px] font-semibold text-slate-900">Conversation</h2>
      </header>
      <ol className="min-h-0 flex-1 space-y-0 overflow-y-auto px-4 py-3 max-xl:max-h-[70vh]">
        {r.comments.map((c) => (
          <CommentView key={c.id} c={c} r={r} isLatestProposal={c.id === latestProposalId} />
        ))}
        <li ref={end} aria-hidden className="list-none" />
      </ol>
      <form
        className="space-y-2 border-t border-slate-200 bg-slate-50/60 p-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) post.mutate();
        }}
      >
        {sent && (
          <Segmented
            label="Message type"
            value={mode}
            onChange={setMode}
            options={[
              { id: "chat", label: "Ask the agent" },
              { id: "change", label: "Change what's requested" },
            ]}
          />
        )}
        <textarea
          aria-label="Message"
          className={cx(inputCls, "min-h-[64px]")}
          placeholder={placeholder}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && text.trim()) post.mutate();
          }}
        />
        <div className="flex items-center justify-between">
          <span className="text-2xs text-slate-500">⌘ Enter to send</span>
          <Button variant="primary" size="sm" busy={post.isPending} disabled={!text.trim()}>
            Send
          </Button>
        </div>
        <ErrorText error={post.error} />
      </form>
    </section>
  );
}

const WHO_ICON: Record<string, { icon: IconName; cls: string }> = {
  me: { icon: "user", cls: "bg-brand-600 text-white" },
  agent: { icon: "sparkle", cls: "bg-violet-100 text-violet-700" },
  provider: { icon: "mail", cls: "bg-amber-100 text-amber-800" },
  system: { icon: "shield", cls: "bg-slate-100 text-slate-600" },
};

function Bubble({ who, tone, at, children }: { who: string; tone: "me" | "agent" | "provider" | "system"; at: string; children: React.ReactNode }) {
  const w = WHO_ICON[tone]!;
  return (
    <li className="relative flex gap-3 pb-4 before:absolute before:bottom-0 before:left-[13px] before:top-8 before:w-px before:bg-slate-200 last-of-type:before:hidden">
      <span className={cx("relative z-10 grid h-7 w-7 shrink-0 place-items-center rounded-full ring-4 ring-white", w.cls)}>
        <Icon name={w.icon} size={13} />
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex items-baseline justify-between gap-2 text-xs">
          <span className="font-semibold text-slate-800">{who}</span>
          <time className="shrink-0 tabular-nums text-slate-500">{fmtTime(at)}</time>
        </div>
        <div className={cx("mt-1 text-[13px] leading-relaxed text-slate-700", tone === "provider" && "rounded-md border border-amber-200 bg-amber-50/50 px-3 py-2", tone === "me" && "rounded-md bg-brand-50 px-3 py-2")}>{children}</div>
      </div>
    </li>
  );
}

/** API failures carry raw provider errors; show a plain sentence and keep the detail one click away. */
function SystemText({ body }: { body: string }) {
  const m = body.match(/^(.*?)(?:\(|: )?((?:check|classify|scope|extract)?:? ?API error:.*?\}\}\)?)(.*)$/s);
  if (!m) return <p className="whitespace-pre-wrap">{body}</p>;
  const summary = /credit|quota|429/i.test(m[2]!) ? "The AI service is unavailable (usage limit reached)." : "The AI service returned an error.";
  return (
    <div className="space-y-1.5">
      <p className="whitespace-pre-wrap">
        {m[1]!.replace(/[:(]\s*$/, "").trim()}. {summary} {m[3]!.replace(/^[).;\s]+/, "").replace(/^./, (ch) => ch.toUpperCase())}
      </p>
      <Disclosure summary="Technical details">
        <pre className="mail rounded bg-slate-50 p-2 text-slate-600">{m[2]}</pre>
      </Disclosure>
    </div>
  );
}

/** Things the system did. Shown as one-line notes so the conversation stays readable. */
const EVENT_KINDS = new Set([
  "checklist_confirmed", "email_sent", "check_result", "requester_notice", "initial", "escalation", "override", "manual_followup",
  "question_answered", "closed_notice", "change_notice", "auto_reply", "provider_upload", "provider_closed",
]);
const PROBLEM_KINDS = new Set(["error", "check_error", "email_failed", "email_uncertain"]);

function EventRow({ c, problem }: { c: Comment; problem?: boolean }) {
  return (
    <li className={cx("flex items-start gap-3 pb-3 pl-[7px] text-xs", problem ? "text-red-800" : "text-slate-500")}>
      <span className={cx("relative z-10 mt-1 h-3.5 w-3.5 shrink-0 rounded-full border-2 bg-white", problem ? "border-red-400" : "border-slate-300")} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="min-w-0">{problem ? <SystemText body={c.body} /> : c.body}</span>
          <time className="shrink-0 tabular-nums">{fmtTime(c.created_at)}</time>
        </div>
      </div>
    </li>
  );
}

function CommentView({ c, r, isLatestProposal }: { c: Comment; r: RequestDetail; isLatestProposal: boolean }) {
  if (EVENT_KINDS.has(c.kind)) return <EventRow c={c} />;
  if (PROBLEM_KINDS.has(c.kind)) return <EventRow c={c} problem />;
  const who = c.author === "requester" ? "You" : c.author === "agent" ? "Agent" : c.author === "provider" ? "Provider" : "System";
  const tone = c.author === "requester" ? "me" : c.author === "agent" ? "agent" : c.author === "provider" ? "provider" : "system";
  switch (c.kind) {
    case "scope_proposal":
      return (
        <Bubble who={who} tone={tone} at={c.created_at}>
          <p className="whitespace-pre-wrap">{c.body}</p>
          <ProposalCard c={c} r={r} active={isLatestProposal} />
        </Bubble>
      );
    case "email_draft": {
      const m = r.messages.find((x) => x.id === c.payload.message_id);
      return (
        <Bubble who={who} tone={tone} at={c.created_at}>
          <p className="mb-2">{c.body}</p>
          {m && (m.status === "draft" ? <SendDraft r={r} messageId={m.id} /> : <OutboundView m={m} compact />)}
        </Bubble>
      );
    }
    case "handback":
      return (
        <Bubble who={who} tone={tone} at={c.created_at}>
          <Handback c={c} />
        </Bubble>
      );
    case "question_for_requester":
      return (
        <Bubble who={who} tone={tone} at={c.created_at}>
          <p className="whitespace-pre-wrap">{c.body}</p>
          <AnswerQuestion r={r} questionId={c.payload.question_id} />
        </Bubble>
      );
    case "provider_email":
    case "late_reply":
      return (
        <Bubble who={`${who} · email`} tone={tone} at={c.created_at}>
          <p className="whitespace-pre-wrap">{c.body}</p>
          {c.payload.sender_is_owner === false && <Badge tone="amber">sent by someone not listed as an owner</Badge>}
        </Bubble>
      );
    case "chat_reply":
    case "chat":
      return (
        <Bubble who={c.kind === "chat" ? "You · question" : "Agent · answer"} tone={tone} at={c.created_at}>
          <p className="whitespace-pre-wrap">{c.body}</p>
        </Bubble>
      );
    default:
      return (
        <Bubble who={c.kind === "message" ? who : `${who} · ${c.kind.replace(/_/g, " ")}`} tone={tone} at={c.created_at}>
          {c.author === "system" ? <SystemText body={c.body} /> : <p className="whitespace-pre-wrap">{c.body}</p>}
        </Bubble>
      );
  }
}

function ProposalCard({ c, r, active }: { c: Comment; r: RequestDetail; active: boolean }) {
  const qc = useQueryClient();
  const v: Version | null = r.proposed_version && r.proposed_version.id === c.payload.version_id ? r.proposed_version : null;
  const [editing, setEditing] = useState(false);
  const [items, setItems] = useState<DraftItem[]>([]);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [due, setDue] = useState("");
  const [cc, setCc] = useState(false);
  const start = () => {
    if (!v) return;
    setItems(v.items.length ? toDraft(v.items) : [{ kind: "document", description: "", criteria: emptyCriteria(), subpoints: [] }]);
    setEmail(v.provider_email ?? "");
    setName(v.provider_name ?? "");
    setDue(v.due_date ?? "");
    setEditing(true);
  };
  const save = useMutation({
    mutationFn: () => api.put<{ version_id: number }>(`/api/requests/${r.id}/versions/${v!.id}`, { items, provider_email: email, provider_name: name, due_date: due || null }),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["request", r.id] });
    },
  });
  const confirm = useMutation({
    mutationFn: () => api.post(`/api/requests/${r.id}/confirm`, { version_id: v!.id, cc_requester: cc }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["request", r.id] }),
  });
  const questions: string[] = c.payload.questions ?? [];
  const assumptions: string[] = c.payload.assumptions ?? [];
  if (!v || !active) {
    return <p className="mt-1 text-xs text-slate-400">Checklist v{r.versions.find((x) => x.id === c.payload.version_id)?.number ?? "?"} ({r.versions.find((x) => x.id === c.payload.version_id)?.status ?? "superseded"})</p>;
  }
  return (
    <div className="mt-2 space-y-3 rounded-md border border-slate-200 bg-white p-3">
      {questions.length > 0 && (
        <div className="rounded bg-amber-50 p-2 text-sm text-amber-900">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide">Questions for you</p>
          <ul className="list-disc space-y-0.5 pl-5">
            {questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
          <p className="mt-1 text-xs">Reply below, or edit the checklist yourself.</p>
        </div>
      )}
      {editing ? (
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-3">
            <Field label="Provider email">
              <input className={inputCls} value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Provider name">
              <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Due date">
              <input type="date" className={inputCls} value={due} onChange={(e) => setDue(e.target.value)} />
            </Field>
          </div>
          <ChecklistEditor items={items} onChange={setItems} />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setEditing(false)}>
              Discard
            </Button>
            <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
              Save as new version
            </Button>
          </div>
          <ErrorText error={save.error} />
        </div>
      ) : (
        <>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
            <dt className="text-slate-400">Provider</dt>
            <dd>{v.provider_email ? `${v.provider_name ?? ""} <${v.provider_email}>` : <span className="text-red-600">missing</span>}</dd>
            <dt className="text-slate-400">Due</dt>
            <dd>{v.due_date ? fmtDate(v.due_date) : "none"}</dd>
          </dl>
          {v.items.length > 0 ? <ChecklistView items={v.items} /> : <p className="text-sm text-slate-500">No items yet.</p>}
          {assumptions.length > 0 && (
            <div className="text-xs text-slate-600">
              <p className="font-semibold">Assumptions</p>
              <ul className="list-disc pl-5">
                {assumptions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
            <Button size="sm" onClick={start}>
              Edit
            </Button>
            {!r.current_version && (
              <label className="flex items-center gap-1.5 text-xs text-slate-600">
                <input type="checkbox" checked={cc} onChange={(e) => setCc(e.target.checked)} /> Cc me on emails
              </label>
            )}
            <Button size="sm" variant="primary" className="ml-auto" disabled={!v.items.length || !v.provider_email} busy={confirm.isPending} onClick={() => confirm.mutate()}>
              {r.current_version ? `Confirm v${v.number} and notify provider` : "Confirm checklist"}
            </Button>
          </div>
          {(!v.items.length || !v.provider_email) && (
            <p className="text-xs text-amber-800">
              To confirm, {[!v.provider_email && "add the provider's email", !v.items.length && "add at least one item"].filter(Boolean).join(" and ")}. Click Edit.
            </p>
          )}
          <ErrorText error={confirm.error} />
        </>
      )}
    </div>
  );
}

function SendDraft({ r, messageId }: { r: RequestDetail; messageId: number }) {
  const qc = useQueryClient();
  const m = r.messages.find((x) => x.id === messageId)!;
  const send = useMutation({ mutationFn: () => api.post(`/api/requests/${r.id}/send`, { message_id: m.id }), onSuccess: () => qc.invalidateQueries({ queryKey: ["request", r.id] }) });
  return (
    <>
      <DraftEditor m={m} onSend={r.state === "ready_to_send" ? () => send.mutate() : undefined} sendLabel="Approve and send" busy={send.isPending} />
      <ErrorText error={send.error} />
    </>
  );
}

function AnswerQuestion({ r, questionId }: { r: RequestDetail; questionId: number }) {
  const qc = useQueryClient();
  const q = r.questions.find((x) => x.id === questionId);
  const [text, setText] = useState("");
  const m = useMutation({ mutationFn: () => api.post(`/api/requests/${r.id}/answer-question`, { question_id: questionId, answer: text }), onSuccess: () => qc.invalidateQueries({ queryKey: ["request", r.id] }) });
  if (!q) return null;
  if (q.status !== "waiting_requester")
    return (
      <p className="mt-2 rounded bg-slate-50 px-2 py-1 text-xs text-slate-600">
        Answered: {q.answer} {q.delivered_at ? "· sent to the provider" : "· goes out with the next message"}
      </p>
    );
  return (
    <div className="mt-2 flex gap-2">
      <input className={inputCls} placeholder="Your answer for the provider" value={text} onChange={(e) => setText(e.target.value)} />
      <Button size="sm" variant="primary" disabled={!text.trim()} busy={m.isPending} onClick={() => m.mutate()}>
        Answer
      </Button>
    </div>
  );
}

/** "file.pdf p.1, p.2; other.xlsx sheet 'A'": one entry per file, each location once. */
function evidenceSummary(ev: { filename: string; location: string; visual?: boolean; verified?: boolean }[]) {
  const by = new Map<string, Set<string>>();
  for (const e of ev) {
    const locs = by.get(e.filename) ?? new Set<string>();
    if (e.location) locs.add(e.location + (e.visual && !e.verified ? " (visual)" : ""));
    by.set(e.filename, locs);
  }
  return [...by].map(([f, l]) => `${f}${l.size ? ` ${[...l].join(", ")}` : ""}`).join("; ");
}

function Handback({ c }: { c: Comment }) {
  const p = c.payload;
  return (
    <div className="space-y-2">
      <p className="font-medium">{c.body}</p>
      <p className="text-xs text-slate-500">
        {p.met} of {p.total} items met · {p.files?.length ?? 0} file(s)
      </p>
      <ul className="space-y-1.5">
        {(p.items ?? []).map((it: any) => (
          <li key={it.key} className="rounded bg-white px-2 py-1.5 text-xs ring-1 ring-slate-200">
            <div className="flex items-start justify-between gap-2">
              <span>{it.description}</span>
              <VerdictBadge verdict={it.verdict} />
            </div>
            {it.evidence?.length > 0 && <p className="mt-0.5 text-slate-500">{evidenceSummary(it.evidence)}</p>}
            {it.verdict !== "met" && it.missing?.map((m: string, i: number) => <p key={i} className="text-red-700">• {m}</p>)}
          </li>
        ))}
      </ul>
      {p.suspicious?.length > 0 && (
        <div className="rounded bg-red-50 p-2 text-xs text-red-800">
          <p className="font-semibold">Suspicious content in what the provider sent (ignored as instructions):</p>
          {p.suspicious.map((s: any, i: number) => (
            <p key={i}>
              {s.location}: “{s.quote}”
            </p>
          ))}
        </div>
      )}
      <FlagList flags={p.flags ?? []} />
    </div>
  );
}

// --------------------------------------------------------------------------- side tabs

function LatestSuspicious({ r }: { r: RequestDetail }) {
  const chk = r.checks.find((c) => c.status === "checked");
  if (!chk?.suspicious?.length) return null;
  return (
    <div className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-800">
      <p className="mb-1 font-semibold">Instruction-like text found in the provider's content. It was treated as evidence only, never as instructions.</p>
      {chk.suspicious.map((s, i) => (
        <p key={i}>
          {s.location}: “{s.quote}”
        </p>
      ))}
    </div>
  );
}

function Questions({ r }: { r: RequestDetail }) {
  if (!r.questions.length) return null;
  return (
    <Card title="Provider questions">
      <ul className="space-y-2 text-sm">
        {r.questions.map((q) => (
          <li key={q.id}>
            <p className="font-medium">Q: {q.question}</p>
            <p className="text-slate-600">{q.answer ? `A: ${q.answer}` : <span className="text-amber-700">Waiting for your answer (see thread)</span>}</p>
            <p className="text-xs text-slate-400">
              {q.status.replace(/_/g, " ")}
              {q.delivered_at && ` · delivered ${fmtTime(q.delivered_at)}`}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Files({ files }: { files: EvidenceFile[] }) {
  const top = files.filter((f) => !f.parent_file_id);
  const [open, setOpen] = useState<number | null>(null);
  if (!top.length) return <Empty>Nothing received yet.</Empty>;
  return (
    <ul className="-my-2 divide-y divide-slate-100">
      {top.map((f) => {
        const children = files.filter((x) => x.parent_file_id === f.id);
        const problem = !f.accepted ? "Rejected" : f.status === "unreadable" ? "Unreadable" : f.status === "error" ? "Couldn't read" : null;
        return (
          <li key={f.id} className="py-2">
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
              <Icon name={f.kind === "text" ? "mail" : "file"} className="text-slate-500" />
              <span className="min-w-0 truncate text-[13px] font-medium text-slate-800">{f.kind === "text" ? "Message" : f.filename}</span>
              {problem && <Badge tone="red">{problem}</Badge>}
              <span className="text-xs text-slate-500">
                {fmtTime(f.created_at)}
                {f.pages ? ` · ${f.pages} pages` : ""}
                {f.size ? ` · ${bytes(f.size)}` : ""}
              </span>
              <span className="ml-auto flex gap-3">
                {(f.images.length > 0 || f.kind === "text") && (
                  <button className="text-xs font-medium text-brand-700 hover:underline" onClick={() => setOpen(open === f.id ? null : f.id)}>
                    {open === f.id ? "Hide" : "View"}
                  </button>
                )}
                {f.kind === "file" && f.accepted && (
                  <a className="text-xs font-medium text-brand-700 hover:underline" href={`/api/files/${f.id}/download`}>
                    Download
                  </a>
                )}
              </span>
            </div>
            {f.reason && <p className="mt-1 pl-6 text-xs text-red-700">{f.reason}</p>}
            {f.flags?.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1 pl-6">
                {f.flags.map((fl, i) => (
                  <Badge key={i} tone="red" title={fl.quote}>
                    {fl.code.replace(/_/g, " ")} {fl.location}
                  </Badge>
                ))}
              </div>
            )}
            {children.length > 0 && <p className="mt-1 pl-6 text-xs text-slate-500">Contains: {children.map((c) => c.filename).join(", ")}</p>}
            {open === f.id && (
              <div className="mt-2 space-y-2 pl-6">
                {f.text && <pre className="mail rounded bg-slate-50 p-2">{f.text}</pre>}
                <div className="grid gap-2 sm:grid-cols-2">
                  {f.images.map((im) => (
                    <figure key={im.index}>
                      <img src={`/api/files/${f.id}/images/${im.index}`} alt={im.label} className="rounded border border-slate-200" loading="lazy" />
                      <figcaption className="text-2xs text-slate-500">{im.label}</figcaption>
                    </figure>
                  ))}
                </div>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function Emails({ r }: { r: RequestDetail }) {
  const items = [
    ...r.messages.filter((m) => m.status !== "draft" && m.status !== "cancelled").map((m) => ({ at: m.sent_at ?? m.created_at, out: m, in: null })),
    ...r.inbound.map((m) => ({ at: m.received_at, out: null, in: m })),
  ].sort((a, b) => a.at.localeCompare(b.at));
  return (
    <div className="space-y-3">
      {r.conversations.length > 0 && (
        <p className="text-xs text-slate-500">
          Replies go to:{" "}
          {r.conversations.map((c) => (
            <span key={c.id} className="mr-2 font-mono">
              {c.reply_to}
            </span>
          ))}
        </p>
      )}
      {items.length === 0 ? <Empty>No email yet.</Empty> : items.map((x, i) => (x.out ? <OutboundView key={`o${x.out.id}-${i}`} m={x.out} /> : <InboundView key={`i${x.in!.id}`} m={x.in!} />))}
    </div>
  );
}

function Audit({ r }: { r: RequestDetail }) {
  return (
    <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
      <table className="w-full text-xs">
        <tbody className="divide-y divide-slate-100">
          {r.audit.map((a) => (
            <tr key={a.id} className="align-top">
              <td className="whitespace-nowrap px-3 py-1.5 text-slate-400">{fmtTime(a.at)}</td>
              <td className="px-3 py-1.5">
                <Badge tone={a.actor === "requester" ? "blue" : a.actor === "provider" ? "amber" : a.actor === "agent" ? "violet" : "slate"}>{a.actor}</Badge>
              </td>
              <td className="px-3 py-1.5">
                <span className="font-medium text-slate-700">{a.action.replace(/_/g, " ")}</span>
                {a.actor_detail && <span className="text-slate-400"> · {a.actor_detail}</span>}
                <AuditDetail d={a.detail} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AuditDetail({ d }: { d: Record<string, unknown> }) {
  const entries = Object.entries(d ?? {}).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0));
  if (!entries.length) return null;
  return (
    <div className="mt-0.5 text-slate-500">
      {entries.map(([k, v]) => (
        <span key={k} className="mr-2">
          {k}: <span className="text-slate-600">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
        </span>
      ))}
    </div>
  );
}
