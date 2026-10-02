import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, fmtDate, fmtTime, type RequestSummary } from "../api";
import { Avatar, Badge, Button, Card, Empty, ErrorText, Icon, PageHeader, Progress, RefId, Segmented, StateBadge, Stat, cx, flagLabel, inputBase, inputCls, td, th } from "../components/ui";

type Filter = "open" | "attention" | "overdue" | "all";
const FILTERS: { id: Filter; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "attention", label: "Needs you" },
  { id: "overdue", label: "Overdue" },
  { id: "all", label: "All" },
];

const NEEDS_YOU = new Set(["waiting_requester", "ready_to_send", "handed_back"]);
const DONE = new Set(["complete", "closed_by_provider", "accepted", "cancelled"]);
const needsYou = (r: RequestSummary) => NEEDS_YOU.has(r.state) || r.flags.some((f) => f.blocking);

export function RequestsPage() {
  const nav = useNavigate();
  const [composing, setComposing] = useState(false);
  const [text, setText] = useState("");
  const [filter, setFilter] = useState<Filter>("open");
  const [q, setQ] = useState("");
  const list = useQuery({ queryKey: ["requests"], queryFn: () => api.get<RequestSummary[]>("/api/requests") });
  const create = useMutation({
    mutationFn: () => api.post<{ id: number }>("/api/requests", { text }),
    onSuccess: (r) => nav(`/requests/${r.id}`),
  });

  const all = list.data ?? [];
  const counts = useMemo(() => {
    const open = all.filter((r) => !DONE.has(r.state));
    const items = open.reduce((n, r) => n + r.total, 0);
    return {
      open: open.length,
      attention: all.filter(needsYou).length,
      overdue: open.filter((r) => r.overdue_days > 0).length,
      done: all.length - open.length,
      itemsMet: open.reduce((n, r) => n + r.met, 0),
      items,
    };
  }, [all]);

  const rows = useMemo(
    () =>
      all.filter((r) => {
        if (filter === "open" && DONE.has(r.state)) return false;
        if (filter === "attention" && !needsYou(r)) return false;
        if (filter === "overdue" && !(r.overdue_days > 0)) return false;
        if (q && !`${r.label} ${r.owners.map((o) => `${o.email} ${o.name}`).join(" ")}`.toLowerCase().includes(q.toLowerCase())) return false;
        return true;
      }),
    [all, filter, q],
  );

  return (
    <div>
      <PageHeader
        title="Requests"
        meta={list.data && <span>{counts.open} open · {counts.done} closed</span>}
        actions={
          <>
            <Link to="/imports">
              <Button tabIndex={-1}>
                <Icon name="imports" /> Import list
              </Button>
            </Link>
            <Button variant="primary" onClick={() => setComposing(!composing)} aria-expanded={composing}>
              <Icon name="plus" /> New request
            </Button>
          </>
        }
      />

      {composing && (
        <Card title="New request" className="mb-5" actions={<Button size="sm" variant="ghost" onClick={() => setComposing(false)}>Close</Button>}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (text.trim()) create.mutate();
            }}
            className="space-y-3"
          >
            <label className="sr-only" htmlFor="new-request">Describe the request</label>
            <textarea
              id="new-request"
              autoFocus
              className={cx(inputCls, "min-h-[84px]")}
              placeholder="What do you need, from whom, and by when? E.g. “Get the signed 2025 MSA and the current certificate of insurance from Jordan Lee (jordan@acme.example) at Acme Logistics by Oct 17.”"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && text.trim()) create.mutate();
              }}
            />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="flex items-center gap-1.5 text-xs text-slate-600">
                <Icon name="shield" size={14} className="text-slate-500" />
                The agent drafts a checklist for you to confirm. Nothing is sent until you approve the email.
              </p>
              <Button variant="primary" busy={create.isPending} disabled={!text.trim()}>
                Draft checklist
              </Button>
            </div>
            <ErrorText error={create.error} />
          </form>
        </Card>
      )}

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Needs your action" value={counts.attention} tone={counts.attention ? "brand" : "default"} sub="Confirm, send or decide" active={filter === "attention"} onClick={() => setFilter(filter === "attention" ? "open" : "attention")} />
        <Stat label="Overdue" value={counts.overdue} tone={counts.overdue ? "danger" : "default"} sub="Past the due date" active={filter === "overdue"} onClick={() => setFilter(filter === "overdue" ? "open" : "overdue")} />
        <Stat label="Open requests" value={counts.open} sub={`${counts.itemsMet} of ${counts.items} items received`} active={filter === "open"} onClick={() => setFilter("open")} />
        <Stat label="Closed" value={counts.done} tone={counts.done ? "success" : "default"} sub="Complete, accepted or closed" active={filter === "all"} onClick={() => setFilter("all")} />
      </div>

      <div className="rounded-md border border-slate-200 bg-white shadow-xs">
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 px-4 py-2.5">
          <Segmented label="Filter requests" options={FILTERS.map((f) => ({ id: f.id, label: f.label }))} value={filter} onChange={setFilter} />
          <div className="relative w-full max-w-xs">
            <Icon name="search" className="pointer-events-none absolute left-2.5 top-2 text-slate-400" />
            <input aria-label="Search requests or people" className={cx(inputBase, "w-full pl-8")} placeholder="Search requests or people" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <span className="ml-auto text-xs tabular-nums text-slate-500">
            {rows.length} of {all.length}
          </span>
        </div>

        {list.isLoading ? null : rows.length === 0 ? (
          <div className="p-4">
            <Empty icon="requests">{all.length ? "No requests match this view." : "No requests yet. Start one, or import a request list."}</Empty>
          </div>
        ) : (
          <>
            <table className="hidden w-full text-[13px] md:table">
              <thead className="border-b border-slate-200 bg-slate-50/70">
                <tr>
                  <th className={th}>Request</th>
                  <th className={th}>Provider</th>
                  <th className={th}>Status</th>
                  <th className={th}>Received</th>
                  <th className={th}>Due</th>
                  <th className={cx(th, "hidden xl:table-cell")}>Last activity</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((r) => (
                  <tr key={r.id} className="group cursor-pointer hover:bg-slate-50" onClick={() => nav(`/requests/${r.id}`)}>
                    <td className={cx(td, "max-w-[420px]")}>
                      <div className="flex min-w-0 items-center gap-2">
                        {r.external_id && <RefId className="w-10 shrink-0">{r.external_id}</RefId>}
                        <Link to={`/requests/${r.id}`} onClick={(e) => e.stopPropagation()} className="truncate font-medium text-slate-900 group-hover:text-brand-700">
                          {r.title}
                        </Link>
                        {r.flags.slice(0, 2).map((f) => (
                          <Badge key={f.code} tone={f.blocking || f.code === "vague" ? "red" : "amber"} title={f.message}>
                            {flagLabel(f.code)}
                          </Badge>
                        ))}
                      </div>
                    </td>
                    <td className={td}>
                      {r.owners.length ? (
                        <div className="flex items-center gap-2">
                          <Avatar name={r.owners[0]!.name || r.owners[0]!.email} className="h-6 w-6" />
                          <span className="truncate text-slate-700">
                            {r.owners[0]!.name || r.owners[0]!.email}
                            {r.owners.length > 1 && <span className="text-slate-500"> +{r.owners.length - 1}</span>}
                          </span>
                        </div>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className={td}>
                      <StateBadge state={r.state} label={r.state_label} />
                    </td>
                    <td className={td}>{r.total ? <Progress value={r.met} total={r.total} /> : <span className="text-slate-400">—</span>}</td>
                    <td className={cx(td, "whitespace-nowrap")}>
                      <Due r={r} />
                    </td>
                    <td className={cx(td, "hidden whitespace-nowrap text-slate-500 xl:table-cell")}>{fmtTime(r.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="divide-y divide-slate-100 md:hidden">
              {rows.map((r) => (
                <li key={r.id}>
                  <Link to={`/requests/${r.id}`} className="block px-4 py-3 hover:bg-slate-50">
                    <div className="flex items-start justify-between gap-3">
                      <span className="min-w-0">
                        {r.external_id && <RefId className="mr-1.5">{r.external_id}</RefId>}
                        <span className="font-medium text-slate-900">{r.title}</span>
                      </span>
                      <StateBadge state={r.state} label={r.state_label} />
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
                      <span>{r.owners.map((o) => o.name || o.email).join(", ") || "—"}</span>
                      {r.total > 0 && <Progress value={r.met} total={r.total} />}
                      <Due r={r} />
                    </div>
                    {r.flags.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {r.flags.slice(0, 3).map((f) => (
                          <Badge key={f.code} tone={f.blocking || f.code === "vague" ? "red" : "amber"}>
                            {flagLabel(f.code)}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
      <ErrorText error={list.error} />
    </div>
  );
}

function Due({ r }: { r: RequestSummary }) {
  if (!r.due_date) return <span className="text-slate-400">—</span>;
  return r.overdue_days ? (
    <span className="inline-flex items-center gap-1.5 font-medium text-red-700">
      {fmtDate(r.due_date)}
      <Badge tone="red">{r.overdue_days}d late</Badge>
    </span>
  ) : (
    <span className="text-slate-700">{fmtDate(r.due_date)}</span>
  );
}
