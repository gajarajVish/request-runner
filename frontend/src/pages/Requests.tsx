import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, fmtDate, fmtTime, type RequestSummary } from "../api";
import { Badge, Button, Card, Empty, ErrorText, StateBadge, cx, inputBase, inputCls } from "../components/ui";

const FILTERS = [
  { id: "open", label: "Open" },
  { id: "attention", label: "Needs you" },
  { id: "all", label: "All" },
] as const;

const NEEDS_YOU = new Set(["waiting_requester", "ready_to_send", "handed_back"]);
const DONE = new Set(["complete", "closed_by_provider", "accepted", "cancelled"]);

export function RequestsPage() {
  const nav = useNavigate();
  const [text, setText] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("open");
  const [q, setQ] = useState("");
  const list = useQuery({ queryKey: ["requests"], queryFn: () => api.get<RequestSummary[]>("/api/requests") });
  const create = useMutation({
    mutationFn: () => api.post<{ id: number }>("/api/requests", { text }),
    onSuccess: (r) => nav(`/requests/${r.id}`),
  });

  const rows = useMemo(() => {
    const all = list.data ?? [];
    return all.filter((r) => {
      if (filter === "open" && DONE.has(r.state)) return false;
      if (filter === "attention" && !(NEEDS_YOU.has(r.state) || r.flags.some((f) => f.blocking))) return false;
      if (q && !`${r.label} ${r.owners.map((o) => `${o.email} ${o.name}`).join(" ")}`.toLowerCase().includes(q.toLowerCase())) return false;
      return true;
    });
  }, [list.data, filter, q]);

  return (
    <div className="space-y-6">
      <Card title="New request">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) create.mutate();
          }}
          className="space-y-3"
        >
          <textarea
            className={cx(inputCls, "min-h-[84px]")}
            placeholder="Describe what you need and from whom. E.g. “Get the signed 2025 MSA and the current certificate of insurance from Jordan Lee (jordan@acme.example) at Acme Logistics by Oct 17.”"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && text.trim()) create.mutate();
            }}
          />
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-500">The agent drafts a checklist for you to confirm. Nothing is sent until you approve the email.</p>
            <Button variant="primary" busy={create.isPending} disabled={!text.trim()}>
              Start request
            </Button>
          </div>
          <ErrorText error={create.error} />
        </form>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-md border border-slate-300 bg-white p-0.5 shadow-sm">
          {FILTERS.map((f) => (
            <button key={f.id} onClick={() => setFilter(f.id)} className={cx("rounded px-3 py-1 text-sm", filter === f.id ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100")}>
              {f.label}
            </button>
          ))}
        </div>
        <input className={cx(inputBase, "w-full max-w-xs")} placeholder="Search requests or people" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="ml-auto text-sm text-slate-500">{rows.length} shown</span>
      </div>

      {list.isLoading ? null : rows.length === 0 ? (
        <Empty>No requests here yet. Start one above, or import a request list.</Empty>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">Request</th>
                <th className="hidden px-4 py-2 md:table-cell">From</th>
                <th className="px-4 py-2">Status</th>
                <th className="hidden px-4 py-2 sm:table-cell">Items</th>
                <th className="hidden px-4 py-2 sm:table-cell">Due</th>
                <th className="hidden px-4 py-2 lg:table-cell">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2.5">
                    <Link to={`/requests/${r.id}`} className="font-medium text-slate-900 hover:text-brand-700">
                      {r.external_id && <span className="mr-1.5 font-mono text-xs text-slate-500">{r.external_id}</span>}
                      {r.title}
                    </Link>
                    {r.flags.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {r.flags.slice(0, 3).map((f) => (
                          <Badge key={f.code} tone={f.blocking || f.code === "vague" ? "red" : "amber"} title={f.message}>
                            {f.code.replace(/_/g, " ")}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="hidden px-4 py-2.5 text-slate-600 md:table-cell">{r.owners.map((o) => o.name || o.email).join(", ") || <span className="text-slate-400">—</span>}</td>
                  <td className="px-4 py-2.5">
                    <StateBadge state={r.state} label={r.state_label} />
                  </td>
                  <td className="hidden px-4 py-2.5 text-slate-600 sm:table-cell">{r.total ? `${r.met}/${r.total} met` : "—"}</td>
                  <td className="hidden px-4 py-2.5 sm:table-cell">
                    {r.due_date ? <span className={r.overdue_days ? "font-medium text-red-700" : "text-slate-600"}>{fmtDate(r.due_date)}{r.overdue_days ? ` · ${r.overdue_days}d late` : ""}</span> : "—"}
                  </td>
                  <td className="hidden px-4 py-2.5 text-slate-500 lg:table-cell">{fmtTime(r.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorText error={list.error} />
    </div>
  );
}
