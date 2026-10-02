import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtTime, type Inbound, type Me, type RequestSummary } from "../api";
import { InboundView } from "../components/Mail";
import { useMe } from "../components/Shell";
import { Badge, Button, Disclosure, Empty, ErrorText, Field, Icon, PageHeader, Tabs, type Tone, cx, inputCls, td, th } from "../components/ui";

const STATUS: Record<string, { tone: Tone; label: string }> = {
  unmatched: { tone: "amber", label: "Needs assigning" },
  matched: { tone: "green", label: "Matched" },
  processed: { tone: "green", label: "Processed" },
  received: { tone: "slate", label: "Received" },
  processing: { tone: "violet", label: "Processing" },
  ignored: { tone: "slate", label: "Ignored" },
  error: { tone: "red", label: "Error" },
  failed: { tone: "red", label: "Failed" },
  auto_reply: { tone: "slate", label: "Auto-reply" },
  closed_target: { tone: "slate", label: "Request closed" },
};

function statusOf(s: string) {
  return STATUS[s] ?? { tone: "slate" as Tone, label: s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) };
}

export function InboxPage() {
  const me = useMe();
  const [tab, setTab] = useState<"unmatched" | "all">("unmatched");
  const q = useQuery({ queryKey: ["inbound", tab], queryFn: () => api.get<Inbound[]>(`/api/inbound${tab === "unmatched" ? "?status=unmatched" : ""}`) });
  // unmatched mail needs a decision, so it starts expanded; everything else starts collapsed
  const [toggled, setToggled] = useState<Set<number>>(new Set());
  const isOpen = (m: Inbound) => (m.status === "unmatched") !== toggled.has(m.id);
  const toggle = (id: number) =>
    setToggled((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });

  return (
    <div>
      <PageHeader
        eyebrow="Mail"
        title="Inbox"
        meta={<span>Replies that couldn't be matched to a request safely wait here. Mail is never assigned by sender address alone.</span>}
      />
      <div className="mb-4">
        <Tabs
          value={tab}
          onChange={setTab}
          tabs={[
            { id: "unmatched", label: <>Needs assigning{tab === "unmatched" && q.data ? <span className="ml-1.5 tabular-nums text-slate-500">{q.data.length}</span> : null}</> },
            { id: "all", label: "All received mail" },
          ]}
        />
      </div>
      <ErrorText error={q.error} />
      {q.data?.length === 0 ? (
        <Empty icon="inbox">{tab === "unmatched" ? "Nothing waiting. Every reply was matched to its request." : "No mail received yet."}</Empty>
      ) : (
        q.data && (
          <div className="overflow-x-auto rounded-md border border-slate-200 bg-white shadow-xs">
            <table className="w-full text-[13px]">
              <thead className="border-b border-slate-200 bg-slate-50">
                <tr>
                  <th className={cx(th, "w-8 pr-0")} aria-label="Expand" />
                  <th className={cx(th, "hidden w-40 md:table-cell")}>Received</th>
                  <th className={cx(th, "md:w-56")}>From</th>
                  <th className={cx(th, "hidden md:table-cell")}>Subject</th>
                  <th className={cx(th, "w-36")}>Status</th>
                </tr>
              </thead>
              <tbody>
                {q.data.map((m) => {
                  const open = isOpen(m);
                  const st = statusOf(m.status);
                  return (
                    <Fragment key={m.id}>
                      <tr className={cx("cursor-pointer border-b border-slate-100 hover:bg-slate-50", open && "bg-slate-50")} onClick={() => toggle(m.id)}>
                        <td className={cx(td, "pr-0")}>
                          <button
                            className="grid h-6 w-6 place-items-center rounded text-slate-500 hover:bg-slate-200"
                            aria-expanded={open}
                            aria-label={open ? "Hide message" : "Show message"}
                            onClick={(e) => {
                              e.stopPropagation();
                              toggle(m.id);
                            }}
                          >
                            <Icon name="chevronRight" size={14} className={cx("transition-transform", open && "rotate-90")} />
                          </button>
                        </td>
                        <td className={cx(td, "hidden whitespace-nowrap text-xs tabular-nums text-slate-500 md:table-cell")}>{fmtTime(m.received_at)}</td>
                        <td className={cx(td, "max-w-0 md:max-w-56")}>
                          <p className="truncate font-medium text-slate-900">{m.from_name || m.from || "Unknown sender"}</p>
                          {m.from_name && m.from && <p className="truncate text-xs text-slate-500">{m.from}</p>}
                          <p className="truncate text-xs text-slate-800 md:hidden">{m.subject || "(no subject)"}</p>
                          <p className="text-xs tabular-nums text-slate-500 md:hidden">{fmtTime(m.received_at)}</p>
                        </td>
                        <td className={cx(td, "hidden max-w-0 md:table-cell")}>
                          <p className="truncate text-slate-800">{m.subject || <span className="text-slate-400">(no subject)</span>}</p>
                          {m.match_method && <p className="truncate text-xs text-slate-500">Matched by {m.match_method.replace(/_/g, " ")}</p>}
                        </td>
                        <td className={td}>
                          <div className="flex flex-wrap gap-1">
                            <Badge tone={st.tone} dot>
                              {st.label}
                            </Badge>
                            {m.is_auto_reply && m.status !== "auto_reply" && <Badge>Auto-reply</Badge>}
                          </div>
                        </td>
                      </tr>
                      {open && (
                        <tr className="border-b border-slate-200 bg-slate-50">
                          <td />
                          <td colSpan={4} className="space-y-3 pb-4 pl-0 pr-3 pt-1 sm:px-4">
                            {m.status === "unmatched" && <Assign m={m} />}
                            <InboundView m={m} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )
      )}
      {me.data?.dev && <InjectCard me={me.data} />}
    </div>
  );
}

function Assign({ m }: { m: Inbound }) {
  const qc = useQueryClient();
  const convs = useQuery({ queryKey: ["conversations"], queryFn: () => api.get<{ id: number; subject: string; provider: string }[]>("/api/conversations") });
  const [cid, setCid] = useState<string>(m.suggestions?.[0]?.conversation_id ? String(m.suggestions[0].conversation_id) : "");
  const assign = useMutation({ mutationFn: () => api.post(`/api/inbound/${m.id}/assign`, { conversation_id: Number(cid) }), onSuccess: () => qc.invalidateQueries() });
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
      <p className="mb-2 flex items-center gap-1.5 text-[13px] font-medium text-amber-900">
        <Icon name="alert" /> Choose the conversation this reply belongs to. It's processed as soon as you assign it.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1 sm:max-w-md">
          <Field label={m.suggestions?.length ? "Suggested: the same sender has open requests" : "Conversation"}>
            <select className={inputCls} value={cid} onChange={(e) => setCid(e.target.value)}>
              <option value="">Choose…</option>
              {m.suggestions?.map((s) => (
                <option key={`s${s.conversation_id}`} value={s.conversation_id}>
                  ★ {s.provider} · {s.subject}
                </option>
              ))}
              {convs.data
                ?.filter((c) => !m.suggestions?.some((s) => s.conversation_id === c.id))
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.provider} · {c.subject}
                  </option>
                ))}
            </select>
          </Field>
        </div>
        <Button variant="primary" disabled={!cid} busy={assign.isPending} onClick={() => assign.mutate()}>
          Assign and process
        </Button>
      </div>
      <ErrorText error={assign.error} />
    </div>
  );
}

function InjectCard({ me }: { me: Me }) {
  const qc = useQueryClient();
  const reqs = useQuery({ queryKey: ["requests"], queryFn: () => api.get<RequestSummary[]>("/api/requests") });
  const [file, setFile] = useState<File | null>(null);
  const [rid, setRid] = useState("");
  const inject = useMutation({
    mutationFn: () => {
      const f = new FormData();
      f.append("file", file!);
      if (rid) f.append("request_id", rid);
      return api.form<{ inbound_id: number; created: boolean }>("/api/dev/inject", f);
    },
    onSuccess: () => qc.invalidateQueries(),
  });
  const sent = reqs.data?.filter((r) => ["waiting_provider", "needs_more", "checking", "handed_back"].includes(r.state)) ?? [];
  return (
    <section className="mt-6 rounded-md border border-dashed border-amber-300 bg-amber-50/40 px-4 py-3">
      <Disclosure summary={<span className="text-amber-900">Development only: inject a raw .eml</span>}>
        <p className="mb-3 text-xs text-slate-600">
          Runs the file through the same pipeline as real inbound mail ({me.email_provider} webhook). Pick a request to point the message's To and In-Reply-To at its thread, as a real reply would.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <Field label=".eml file">
            <input type="file" accept=".eml,message/rfc822" className={inputCls} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </Field>
          <Field label="Reply to">
            <select className={inputCls} value={rid} onChange={(e) => setRid(e.target.value)}>
              <option value="">Leave headers as they are</option>
              {sent.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </Field>
          <Button variant="primary" disabled={!file} busy={inject.isPending} onClick={() => inject.mutate()}>
            Inject
          </Button>
        </div>
        {inject.data && <p className="mt-2 text-xs text-slate-600">{inject.data.created ? `Received as inbound #${inject.data.inbound_id}.` : `Duplicate of inbound #${inject.data.inbound_id} (same Message-ID), ignored.`}</p>}
        <ErrorText error={inject.error} />
      </Disclosure>
    </section>
  );
}
