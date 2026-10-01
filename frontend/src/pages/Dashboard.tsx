import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, fmtDate, type Dashboard, type ImportListSummary } from "../api";
import { Badge, Card, Empty, StateBadge, cx, inputBase } from "../components/ui";

const STATUSES = [
  ["open", "All open"],
  ["waiting_provider", "Waiting for provider"],
  ["needs_more", "Needs more"],
  ["checking", "Checking"],
  ["handed_back", "Handed back"],
  ["ready_to_send", "Ready to send"],
  ["waiting_requester", "Waiting for you"],
  ["complete", "Complete"],
  ["", "Everything"],
] as const;

export function DashboardPage() {
  const [params, setParams] = useSearchParams();
  const provider = params.get("provider") ?? "";
  const status = params.get("status") ?? "open";
  const overdue = params.get("overdue") === "1";
  const list = params.get("list") ?? "";
  const qs = new URLSearchParams();
  if (provider) qs.set("provider", provider);
  if (status) qs.set("status", status);
  if (overdue) qs.set("overdue", "true");
  if (list) qs.set("list_id", list);
  const d = useQuery({ queryKey: ["dashboard", qs.toString()], queryFn: () => api.get<Dashboard>(`/api/dashboard?${qs}`) });
  const lists = useQuery({ queryKey: ["imports"], queryFn: () => api.get<ImportListSummary[]>("/api/imports") });
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p, { replace: true });
  };
  const data = d.data;
  const open = data ? data.providers.reduce((n, g) => n + g.open, 0) : 0;
  const late = data ? data.providers.reduce((n, g) => n + g.overdue, 0) : 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto text-xl font-semibold">Who's behind</h1>
        <select className={inputBase} value={list} onChange={(e) => set("list", e.target.value)}>
          <option value="">All requests</option>
          {lists.data?.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
        <select className={inputBase} value={provider} onChange={(e) => set("provider", e.target.value)}>
          <option value="">Everyone</option>
          {data?.all_providers.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select className={inputBase} value={status} onChange={(e) => set("status", e.target.value)}>
          {STATUSES.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-sm text-slate-600">
          <input type="checkbox" checked={overdue} onChange={(e) => set("overdue", e.target.checked ? "1" : "")} /> Overdue only
        </label>
      </div>

      {data && (
        <div className="grid gap-3 sm:grid-cols-4">
          <Stat label="People behind" value={data.providers_behind} tone={data.providers_behind ? "text-red-700" : undefined} />
          <Stat label="Overdue items" value={late} tone={late ? "text-red-700" : undefined} />
          <Stat label="Open items shown" value={open} />
          <Stat label="As of" value={fmtDate(data.today)} small />
        </div>
      )}

      {data && data.providers.length === 0 && <Empty>Nothing matches these filters.</Empty>}
      <div className="grid gap-4 lg:grid-cols-2">
        {data?.providers.map((g) => (
          <Card
            key={g.provider.id}
            title={
              <span>
                {g.provider.name || g.provider.email}
                {g.provider.name && <span className="ml-1.5 font-normal text-slate-400">{g.provider.email}</span>}
              </span>
            }
            actions={
              <>
                {g.overdue > 0 ? (
                  <Badge tone="red">
                    {g.overdue} overdue · up to {g.max_days_overdue}d
                  </Badge>
                ) : (
                  <Badge tone="green">on track</Badge>
                )}
                <Badge>{g.open} open</Badge>
              </>
            }
          >
            <ul className="divide-y divide-slate-100">
              {g.items.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2 py-1.5 text-sm">
                  <Link to={`/requests/${r.id}`} className="min-w-0 flex-1 truncate hover:text-brand-700">
                    {r.external_id && <span className="mr-1.5 font-mono text-xs text-slate-500">{r.external_id}</span>}
                    {r.title}
                  </Link>
                  {r.owners.length > 1 && <Badge tone="violet">shared</Badge>}
                  <span className="text-xs text-slate-500">{r.total ? `${r.met}/${r.total}` : ""}</span>
                  <StateBadge state={r.state} label={r.state_label} />
                  <span className={cx("w-28 text-right text-xs", r.overdue_days ? "font-semibold text-red-700" : "text-slate-500")}>
                    {r.overdue_days ? `${r.overdue_days}d overdue` : r.due_date ? `due ${fmtDate(r.due_date)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value, tone, small }: { label: string; value: number | string; tone?: string; small?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={cx(small ? "mt-1 text-base" : "mt-0.5 text-2xl", "font-semibold", tone)}>{value}</p>
    </div>
  );
}
