import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, fmtTime, type AuditEntry, type Outbound } from "../api";
import { OutboundView } from "../components/Mail";
import { Badge, Button, Empty, ErrorText, Icon, PageHeader, Segmented, Tabs, type Tone, cx, inputBase, td, th } from "../components/ui";

const ACTOR_TONE: Record<string, Tone> = { requester: "blue", provider: "amber", agent: "violet", system: "slate" };
const ACTOR_LABEL: Record<string, string> = { requester: "You", provider: "Provider", agent: "Agent", system: "System" };

const MSG_TONE: Record<string, Tone> = { sent: "green", delivered: "green", queued: "slate", sending: "slate", draft: "slate", failed: "red", bounced: "red", cancelled: "slate" };

function sentence(s: string) {
  const t = s.replace(/_/g, " ");
  return t[0]!.toUpperCase() + t.slice(1);
}

export function ActivityPage() {
  const [tab, setTab] = useState<"audit" | "sent">("audit");
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.get<AuditEntry[]>("/api/audit"), enabled: tab === "audit" });
  const sent = useQuery({ queryKey: ["messages"], queryFn: () => api.get<Outbound[]>("/api/messages"), enabled: tab === "sent" });
  return (
    <div>
      <PageHeader title="Audit log" meta={<span>Every action by you, the agent, providers and the system, in order. Entries can't be edited or deleted.</span>} />
      <div className="mb-4">
        <Tabs
          value={tab}
          onChange={setTab}
          tabs={[
            { id: "audit", label: "Audit log" },
            { id: "sent", label: "Outgoing email" },
          ]}
        />
      </div>
      {tab === "audit" && <AuditTable rows={audit.data} loading={audit.isLoading} error={audit.error} />}
      {tab === "sent" && <SentTable rows={sent.data} loading={sent.isLoading} error={sent.error} />}
    </div>
  );
}

function AuditTable({ rows, loading, error }: { rows?: AuditEntry[]; loading: boolean; error: unknown }) {
  const [actor, setActor] = useState<"all" | "requester" | "agent" | "provider" | "system">("all");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(100);
  const shown = useMemo(
    () =>
      (rows ?? []).filter(
        (a) => (actor === "all" || a.actor === actor) && (!q || `${a.action} ${a.actor_detail ?? ""} ${a.request_id ?? ""} ${JSON.stringify(a.detail)}`.toLowerCase().includes(q.toLowerCase())),
      ),
    [rows, actor, q],
  );
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Segmented
          label="Actor"
          value={actor}
          onChange={setActor}
          options={[
            { id: "all", label: "All" },
            { id: "requester", label: "You" },
            { id: "agent", label: "Agent" },
            { id: "provider", label: "Providers" },
            { id: "system", label: "System" },
          ]}
        />
        <div className="relative w-full max-w-xs">
          <Icon name="search" size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input className={cx(inputBase, "w-full pl-8")} placeholder="Filter by action, person or request" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter audit log" />
        </div>
        <span className="ml-auto text-xs tabular-nums text-slate-500">{rows ? `${shown.length} of ${rows.length} entries` : ""}</span>
      </div>
      <ErrorText error={error} />
      {!loading && shown.length === 0 ? (
        <Empty icon="activity">{rows?.length ? "No entries match these filters." : "No activity yet."}</Empty>
      ) : (
        <div className="overflow-x-auto rounded-md border border-slate-200 bg-white shadow-xs">
          <table className="w-full text-[13px]">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className={cx(th, "hidden w-40 sm:table-cell")}>Time</th>
                <th className={cx(th, "w-28")}>Actor</th>
                <th className={cx(th, "hidden w-24 sm:table-cell")}>Request</th>
                <th className={th}>Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {shown.slice(0, limit).map((a) => (
                <tr key={a.id} className="align-top hover:bg-slate-50">
                  <td className={cx(td, "hidden whitespace-nowrap text-xs tabular-nums text-slate-500 sm:table-cell")}>{fmtTime(a.at)}</td>
                  <td className={td}>
                    <Badge tone={ACTOR_TONE[a.actor] ?? "slate"} dot>
                      {ACTOR_LABEL[a.actor] ?? a.actor}
                    </Badge>
                  </td>
                  <td className={cx(td, "hidden whitespace-nowrap sm:table-cell")}>
                    {a.request_id ? (
                      <Link to={`/requests/${a.request_id}`} className="font-mono text-xs font-medium text-brand-700 hover:underline">
                        #{a.request_id}
                      </Link>
                    ) : (
                      <span className="text-slate-300">—</span>
                    )}
                  </td>
                  <td className={td}>
                    <span className="block text-xs tabular-nums text-slate-500 sm:hidden">
                      {fmtTime(a.at)}
                      {a.request_id ? ` · #${a.request_id}` : ""}
                    </span>
                    <span className="font-medium text-slate-900">{sentence(a.action)}</span>
                    {a.actor_detail && <span className="text-slate-500"> · {a.actor_detail}</span>}
                    <Detail d={a.detail} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length > limit && (
            <div className="flex items-center justify-between border-t border-slate-200 px-4 py-2.5 text-xs text-slate-600">
              <span className="tabular-nums">
                Showing {limit} of {shown.length}
              </span>
              <Button size="sm" onClick={() => setLimit(limit + 200)}>
                Show more
              </Button>
            </div>
          )}
        </div>
      )}
    </>
  );
}

function Detail({ d }: { d: Record<string, unknown> }) {
  const entries = Object.entries(d ?? {}).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0));
  if (!entries.length) return null;
  return (
    <dl className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
      {entries.map(([k, v]) => (
        <div key={k} className="flex min-w-0 gap-1">
          <dt className="text-slate-500">{k.replace(/_/g, " ")}</dt>
          <dd className="min-w-0 break-all font-mono text-[11px] text-slate-700">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function SentTable({ rows, loading, error }: { rows?: Outbound[]; loading: boolean; error: unknown }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      <ErrorText error={error} />
      {!loading && !rows?.length ? (
        <Empty icon="mail">No email has been sent yet.</Empty>
      ) : (
        <div className="overflow-x-auto rounded-md border border-slate-200 bg-white shadow-xs">
          <table className="w-full text-[13px]">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className={cx(th, "w-8 pr-0")} aria-label="Expand" />
                <th className={cx(th, "hidden w-40 md:table-cell")}>Sent</th>
                <th className={cx(th, "w-56")}>To</th>
                <th className={cx(th, "hidden md:table-cell")}>Subject</th>
                <th className={cx(th, "hidden w-28 sm:table-cell")}>Type</th>
                <th className={cx(th, "w-24")}>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows?.map((m) => {
                const isOpen = open === m.id;
                return (
                  <Fragment key={m.id}>
                    <tr className={cx("cursor-pointer border-b border-slate-100 hover:bg-slate-50", isOpen && "bg-slate-50")} onClick={() => setOpen(isOpen ? null : m.id)}>
                      <td className={cx(td, "pr-0")}>
                        <button
                          className="grid h-6 w-6 place-items-center rounded text-slate-500 hover:bg-slate-200"
                          aria-expanded={isOpen}
                          aria-label={isOpen ? "Hide email" : "Show email"}
                          onClick={(e) => {
                            e.stopPropagation();
                            setOpen(isOpen ? null : m.id);
                          }}
                        >
                          <Icon name="chevronRight" size={14} className={cx("transition-transform", isOpen && "rotate-90")} />
                        </button>
                      </td>
                      <td className={cx(td, "hidden whitespace-nowrap text-xs tabular-nums text-slate-500 md:table-cell")}>{fmtTime(m.sent_at ?? m.created_at)}</td>
                      <td className={cx(td, "max-w-0 md:max-w-56")}>
                        <p className="truncate text-slate-700">{m.to.join(", ")}</p>
                        <p className="truncate text-xs text-slate-500 md:hidden">
                          {fmtTime(m.sent_at ?? m.created_at)} · {m.subject}
                        </p>
                      </td>
                      <td className={cx(td, "hidden max-w-0 truncate font-medium text-slate-900 md:table-cell")}>{m.subject}</td>
                      <td className={cx(td, "hidden text-xs text-slate-600 sm:table-cell")}>{sentence(m.kind)}</td>
                      <td className={td}>
                        <Badge tone={MSG_TONE[m.status] ?? "slate"} dot>
                          {sentence(m.status)}
                        </Badge>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="border-b border-slate-200 bg-slate-50">
                        <td />
                        <td colSpan={5} className="pb-4 pl-0 pr-3 pt-1 sm:px-4">
                          <OutboundView m={m} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
