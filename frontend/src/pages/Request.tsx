import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, bytes, fmtDate, fmtTime, type Comment, type EvidenceFile, type Item, type RequestDetail, type Version } from "../api";
import { ChecklistEditor, ChecklistView, toDraft, type DraftItem } from "../components/Checklist";
import { DraftEditor, InboundView, OutboundView } from "../components/Mail";
import { Avatar, Badge, Button, Card, Disclosure, Empty, ErrorText, Field, FlagList, Icon, type IconName, Menu, Modal, Progress, RefId, Segmented, Spinner, StateBadge, Tabs, VerdictBadge, cx, inputCls } from "../components/ui";

const OPEN_WITH_PROVIDER = new Set(["waiting_provider", "checking", "needs_more", "handed_back"]);
const TERMINAL = new Set(["complete", "closed_by_provider", "accepted", "cancelled"]);

export function RequestPage() {
  const id = Number(useParams().id);
  const q = useQuery({ queryKey: ["request", id], queryFn: () => api.get<RequestDetail>(`/api/requests/${id}`) });
  const [tab, setTab] = useState<"checklist" | "files" | "email" | "audit">("checklist");
  const [override, setOverride] = useState<Item | null>(null);

  if (q.isLoading) return null;
  if (q.error || !q.data) return <ErrorText error={q.error ?? "not found"} />;
  const r = q.data;
  const checking = r.state === "checking" || r.checks.some((c) => c.status === "pending" || c.status === "checking");

  return (
    <div>
      <Header r={r} />
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(360px,1fr)]">
        <section className="min-w-0 rounded-md border border-slate-200 bg-white shadow-xs">
          <div className="px-4">
            <Tabs
              value={tab}
              onChange={setTab}
              tabs={[
                { id: "checklist", label: <TabLabel text="Checklist" n={r.total ? `${r.met}/${r.total}` : undefined} /> },
                { id: "files", label: <TabLabel text="Evidence" n={r.files.filter((f) => !f.parent_file_id).length} /> },
                { id: "email", label: <TabLabel text="Email" n={r.messages.filter((m) => m.status !== "draft").length + r.inbound.length} /> },
                { id: "audit", label: <TabLabel text="Audit log" n={r.audit.length} /> },
              ]}
            />
          </div>
          <div className="p-4">
            {tab === "checklist" && (
              <div className="space-y-4">
                {checking && (
                  <div className="flex items-center gap-2 rounded-md border border-violet-200 bg-violet-50 px-3 py-2 text-[13px] text-violet-900">
                    <Spinner /> Checking what was received…
                  </div>
                )}
                <LatestSuspicious r={r} />
                {r.current_version ? (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                      <span>
                        Confirmed checklist <span className="font-medium text-slate-700">v{r.current_version.number}</span>
                        {r.current_version.confirmed_at && ` · ${fmtTime(r.current_version.confirmed_at)}`}
                      </span>
                      <span>Sent to {r.current_version.provider_email}</span>
                    </div>
                    <ChecklistView items={r.current_version.items} files={r.files} onOverride={OPEN_WITH_PROVIDER.has(r.state) ? setOverride : undefined} />
                  </>
                ) : r.proposed_version ? (
                  <>
                    <p className="text-xs text-slate-500">
                      Proposed checklist <span className="font-medium text-slate-700">v{r.proposed_version.number}</span> · review and confirm it in the activity panel
                    </p>
                    <ChecklistView items={r.proposed_version.items} />
                    {r.proposed_version.items.length === 0 && <Empty>No items yet. Answer the agent's questions in the activity panel.</Empty>}
                  </>
                ) : (
                  <Empty icon="sparkle">The agent is drafting a checklist…</Empty>
                )}
                {r.current_version && r.proposed_version && (
                  <p className="rounded-md border border-brand-200 bg-brand-50 px-3 py-2 text-xs text-brand-900">
                    A revised checklist (v{r.proposed_version.number}) is waiting for your confirmation in the activity panel.
                  </p>
                )}
                <Questions r={r} />
              </div>
            )}
            {tab === "files" && <Files files={r.files} />}
            {tab === "email" && <Emails r={r} />}
            {tab === "audit" && <Audit r={r} />}
          </div>
        </section>
        <Thread r={r} />
      </div>
      <OverrideModal r={r} item={override} onClose={() => setOverride(null)} />
    </div>
  );
}

function TabLabel({ text, n }: { text: string; n?: number | string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {text}
      {n !== undefined && <span className="rounded bg-slate-100 px-1.5 text-2xs font-semibold tabular-nums text-slate-600">{n}</span>}
    </span>
  );
}

// --------------------------------------------------------------------------- header & actions

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 px-4 py-2.5">
      <dt className="text-2xs font-semibold uppercase tracking-[0.08em] text-slate-500">{label}</dt>
      <dd className="mt-1 text-[13px] text-slate-800">{children}</dd>
    </div>
  );
}

function Header({ r }: { r: RequestDetail }) {
  const qc = useQueryClient();
  const [modal, setModal] = useState<null | "cancel" | "accept" | "due">(null);
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
            {r.external_id && <RefId className="rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[13px]">{r.external_id}</RefId>}
            {r.title}
            <StateBadge state={r.state} label={r.state_label} />
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {r.state === "handed_back" && (
            <Button variant="primary" onClick={() => act.mutate({ path: "resume" })} title="Keep waiting without further automatic follow-ups">
              Keep waiting
            </Button>
          )}
          {open && (
            <>
              <Button onClick={() => act.mutate({ path: "recheck" })} busy={act.isPending && act.variables?.path === "recheck"}>
                <Icon name="refresh" /> Re-check
              </Button>
              <Button
                variant={r.state === "handed_back" ? "secondary" : "primary"}
                onClick={() => act.mutate({ path: "manual-followup" })}
                busy={act.isPending && act.variables?.path === "manual-followup"}
                title="Send a follow-up now (doesn't use the automatic limit)"
              >
                <Icon name="send" /> Follow up now
              </Button>
            </>
          )}
          <Menu
            items={[
              open && { label: "Accept as is", hint: "Close with what was received", onClick: () => setModal("accept") },
              !TERMINAL.has(r.state) && { label: "Change due date", onClick: () => setModal("due") },
              !TERMINAL.has(r.state) && { label: "Cancel request", danger: true, onClick: () => setModal("cancel") },
            ]}
          />
        </div>
      </div>
      <dl className="grid grid-cols-2 divide-slate-200 rounded-md border border-slate-200 bg-white shadow-xs sm:grid-cols-3 lg:grid-cols-5 lg:divide-x">
        <Fact label={r.owners.length > 1 ? (r.ownership_mode === "all" ? "Providers (all must respond)" : "Providers (any one)") : "Provider"}>
          {r.owners.length ? (
            <div className="space-y-1">
              {r.owners.map((o) => (
                <div key={o.provider_id} className="flex min-w-0 items-center gap-2">
                  <Avatar name={o.name || o.email} className="h-6 w-6" />
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{o.name || o.email}</span>
                    {o.name && <span className="block truncate text-xs text-slate-500">{o.email}</span>}
                  </span>
                  {o.closed_at && <Badge>Said that's all</Badge>}
                </div>
              ))}
            </div>
          ) : (
            <span className="text-slate-400">Not set</span>
          )}
        </Fact>
        <Fact label="Due">
          {r.due_date ? (
            <span className={cx("inline-flex items-center gap-1.5", r.overdue_days ? "font-medium text-red-700" : "")}>
              {fmtDate(r.due_date)}
              {r.overdue_days > 0 && <Badge tone="red">{r.overdue_days}d overdue</Badge>}
            </span>
          ) : (
            <span className="text-slate-400">None</span>
          )}
        </Fact>
        <Fact label="Items received">{r.total ? <Progress value={r.met} total={r.total} /> : <span className="text-slate-400">—</span>}</Fact>
        <Fact label="Automatic follow-ups">
          <span title="Automatic contacts (reminders, follow-ups, overdue and change notices) used, out of the limit" className="tabular-nums">
            {r.auto_contact_count} of {r.max_auto_contacts} used
          </span>
        </Fact>
        <Fact label="Escalates to">{r.backup_email ? <span className="block truncate">{r.backup_email}</span> : <span className="text-slate-400">No backup owner</span>}</Fact>
      </dl>
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
      {r.aliases.length > 0 && <p className="text-xs text-slate-500">Also known as: {r.aliases.join(", ")}</p>}
      <FlagList flags={r.flags} />
      <ErrorText error={act.error} />
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
  useEffect(() => end.current?.scrollIntoView({ block: "nearest" }), [r.comments.length]);
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
        <h2 className="text-[13px] font-semibold text-slate-900">Activity</h2>
        <span className="text-xs text-slate-500">{r.comments.length} events</span>
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

function CommentView({ c, r, isLatestProposal }: { c: Comment; r: RequestDetail; isLatestProposal: boolean }) {
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
    setItems(toDraft(v.items));
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
    <div className="space-y-2">
      {top.map((f) => {
        const children = files.filter((x) => x.parent_file_id === f.id);
        return (
          <div key={f.id} className="rounded-md border border-slate-200 bg-white p-3">
            <div className="flex flex-wrap items-center gap-2">
              {f.kind === "text" ? <Badge tone="violet">typed answer</Badge> : <Badge>{f.detected_type ?? "file"}</Badge>}
              <span className="text-sm font-medium">{f.filename}</span>
              <Badge tone={f.status === "ok" ? "green" : f.status === "unreadable" ? "violet" : f.status === "pending" ? "slate" : "red"}>{f.accepted ? f.status : "rejected"}</Badge>
              <span className="text-xs text-slate-400">
                {f.source} · {fmtTime(f.created_at)} {f.size ? `· ${bytes(f.size)}` : ""} {f.pages ? `· ${f.pages} pages` : ""}
              </span>
              <span className="ml-auto flex gap-2">
                {f.kind === "file" && f.accepted && (
                  <a className="text-xs font-medium text-brand-700 hover:underline" href={`/api/files/${f.id}/download`}>
                    Download
                  </a>
                )}
                {(f.images.length > 0 || f.kind === "text") && (
                  <button className="text-xs font-medium text-brand-700 hover:underline" onClick={() => setOpen(open === f.id ? null : f.id)}>
                    {open === f.id ? "Hide" : "View"}
                  </button>
                )}
              </span>
            </div>
            {f.reason && <p className="mt-1 text-xs text-red-700">{f.reason}</p>}
            {f.flags?.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {f.flags.map((fl, i) => (
                  <Badge key={i} tone="red" title={fl.quote}>
                    {fl.code.replace(/_/g, " ")} {fl.location}
                  </Badge>
                ))}
              </div>
            )}
            {children.length > 0 && <p className="mt-1 text-xs text-slate-500">Contains: {children.map((c) => c.filename).join(", ")}</p>}
            {open === f.id && (
              <div className="mt-2 space-y-2">
                {f.text && <pre className="mail rounded bg-slate-50 p-2">{f.text}</pre>}
                <div className="grid gap-2 sm:grid-cols-2">
                  {f.images.map((im) => (
                    <figure key={im.index}>
                      <img src={`/api/files/${f.id}/images/${im.index}`} alt={im.label} className="rounded border border-slate-200" loading="lazy" />
                      <figcaption className="text-[11px] text-slate-500">{im.label}</figcaption>
                    </figure>
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
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
