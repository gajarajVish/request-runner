import { Fragment, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, fmtDate, type Dashboard, type ImportListSummary, type RequestSummary } from "../api";
import { Avatar, Badge, Empty, ErrorText, Icon, PageHeader, Progress, RefId, StateBadge, Stat, cx, inputBase, td, th } from "../components/ui";

const STATUSES = [
  ["open", "All open"],
  ["waiting_provider", "Awaiting provider"],
  ["needs_more", "Incomplete"],
  ["checking", "Reviewing evidence"],
  ["handed_back", "Needs your decision"],
  ["ready_to_send", "Ready to send"],
  ["waiting_requester", "Needs your input"],
  ["complete", "Complete"],
  ["", "Everything"],
] as const;

// Aging buckets for the per-person status bar. Status colors carry state, so each segment
// also has a label in the legend and the tooltip; the counts are in the table columns too.
const BUCKETS = [
  { id: "overdue", label: "Overdue", color: "bg-red-600" },
  { id: "attention", label: "Incomplete or needs decision", color: "bg-amber-500" },
  { id: "waiting", label: "Waiting / in progress", color: "bg-slate-400" },
  { id: "done", label: "Complete", color: "bg-emerald-600" },
] as const;
type Bucket = (typeof BUCKETS)[number]["id"];

const DONE = new Set(["complete", "accepted", "closed_by_provider", "cancelled"]);

function bucketOf(r: RequestSummary): Bucket {
  if (DONE.has(r.state)) return "done";
  if (r.overdue_days > 0) return "overdue";
  if (r.state === "needs_more" || r.state === "handed_back") return "attention";
  return "waiting";
}

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
  const onTime = open ? Math.round(((open - late) / open) * 100) : 100;

  return (
    <div>
      <PageHeader
        eyebrow="Follow-up"
        title="Who's behind"
        meta={data && <span>As of {fmtDate(data.today)} · people sorted by days overdue</span>}
        actions={
          <>
            <select aria-label="Request list" className={inputBase} value={list} onChange={(e) => set("list", e.target.value)}>
              <option value="">All requests</option>
              {lists.data?.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
            <select aria-label="Person" className={cx(inputBase, "max-w-48")} value={provider} onChange={(e) => set("provider", e.target.value)}>
              <option value="">Everyone</option>
              {data?.all_providers.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            <select aria-label="Status" className={inputBase} value={status} onChange={(e) => set("status", e.target.value)}>
              {STATUSES.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
            <label className="flex h-8 items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 text-[13px] text-slate-700 shadow-xs">
              <input type="checkbox" className="accent-brand-600" checked={overdue} onChange={(e) => set("overdue", e.target.checked ? "1" : "")} /> Overdue only
            </label>
          </>
        }
      />

      {data && (
        <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Open items" value={open} sub={`across ${data.providers.length} ${data.providers.length === 1 ? "person" : "people"}`} />
          <Stat label="Overdue items" value={late} tone={late ? "danger" : "default"} sub={late ? "past their due date" : "nothing past due"} active={overdue} onClick={() => set("overdue", overdue ? "" : "1")} />
          <Stat label="People behind" value={data.providers_behind} tone={data.providers_behind ? "danger" : "default"} sub="with at least one overdue item" />
          <Stat label="On time" value={`${onTime}%`} tone={onTime < 80 ? "warning" : "success"} sub="of open items not yet overdue" />
        </div>
      )}

      <ErrorText error={d.error} />
      {data && data.providers.length === 0 && <Empty icon="dashboard">Nothing matches these filters.</Empty>}
      {data && data.providers.length > 0 && <ProviderTable groups={data.providers} />}
    </div>
  );
}

function ProviderTable({ groups }: { groups: Dashboard["providers"] }) {
  const [open, setOpen] = useState<Set<number>>(() => new Set(groups.filter((g) => g.overdue > 0).map((g) => g.provider.id)));
  const toggle = (id: number) =>
    setOpen((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  const sorted = [...groups].sort((a, b) => b.max_days_overdue - a.max_days_overdue || b.overdue - a.overdue || b.open - a.open);
  const maxItems = Math.max(...groups.map((g) => g.items.length), 1);

  return (
    <div className="overflow-hidden rounded-md border border-slate-200 bg-white shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-2.5">
        <h2 className="text-[13px] font-semibold text-slate-900">By person</h2>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600" aria-label="Status bar legend">
          {BUCKETS.map((b) => (
            <li key={b.id} className="flex items-center gap-1.5">
              <span className={cx("h-2 w-2 rounded-[2px]", b.color)} aria-hidden />
              {b.label}
            </li>
          ))}
        </ul>
      </div>
      <ul className="divide-y divide-slate-200 md:hidden">
        {sorted.map((g) => {
          const isOpen = open.has(g.provider.id);
          const name = g.provider.name || g.provider.email;
          return (
            <li key={g.provider.id}>
              <button className="w-full space-y-2 px-4 py-3 text-left hover:bg-slate-50" aria-expanded={isOpen} onClick={() => toggle(g.provider.id)}>
                <div className="flex items-center gap-2.5">
                  <Avatar name={name} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-slate-900">{name}</p>
                    <p className="text-xs tabular-nums text-slate-500">
                      {g.open} open{g.overdue ? ` · ${g.overdue} overdue` : ""}
                    </p>
                  </div>
                  {g.max_days_overdue > 0 ? <Badge tone="red">{g.max_days_overdue}d late</Badge> : <Badge tone="green">On track</Badge>}
                  <Icon name="chevronRight" size={14} className={cx("text-slate-400 transition-transform", isOpen && "rotate-90")} />
                </div>
                <StatusBar items={g.items} max={maxItems} />
              </button>
              {isOpen && (
                <div className="px-4 pb-3">
                  <ItemList items={g.items} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-[13px]">
          <thead className="border-b border-slate-200 bg-slate-50">
            <tr>
              <th className={cx(th, "w-8 pr-0")} aria-label="Expand" />
              <th className={th}>Person</th>
              <th className={cx(th, "text-right")}>Open</th>
              <th className={cx(th, "text-right")}>Overdue</th>
              <th className={cx(th, "text-right")}>Most late</th>
              <th className={cx(th, "w-[34%]")}>Items by status</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((g) => {
              const isOpen = open.has(g.provider.id);
              const name = g.provider.name || g.provider.email;
              return (
                <Fragment key={g.provider.id}>
                  <tr className={cx("cursor-pointer border-b border-slate-100 hover:bg-slate-50", isOpen && "bg-slate-50/60")} onClick={() => toggle(g.provider.id)}>
                    <td className={cx(td, "pr-0")}>
                      <button
                        className="grid h-6 w-6 place-items-center rounded text-slate-500 hover:bg-slate-200 hover:text-slate-800"
                        aria-expanded={isOpen}
                        aria-label={`${isOpen ? "Hide" : "Show"} items for ${name}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggle(g.provider.id);
                        }}
                      >
                        <Icon name="chevronRight" size={14} className={cx("transition-transform", isOpen && "rotate-90")} />
                      </button>
                    </td>
                    <td className={td}>
                      <div className="flex items-center gap-2.5">
                        <Avatar name={name} />
                        <div className="min-w-0">
                          <p className="truncate font-medium text-slate-900">{name}</p>
                          {g.provider.name && <p className="truncate text-xs text-slate-500">{g.provider.email}</p>}
                        </div>
                      </div>
                    </td>
                    <td className={cx(td, "text-right tabular-nums text-slate-700")}>{g.open}</td>
                    <td className={cx(td, "text-right tabular-nums")}>{g.overdue ? <span className="font-semibold text-red-700">{g.overdue}</span> : <span className="text-slate-400">0</span>}</td>
                    <td className={cx(td, "text-right tabular-nums")}>
                      {g.max_days_overdue > 0 ? <Badge tone="red">{g.max_days_overdue}d late</Badge> : <Badge tone="green">On track</Badge>}
                    </td>
                    <td className={td}>
                      <StatusBar items={g.items} max={maxItems} />
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="border-b border-slate-200 bg-slate-50/60">
                      <td />
                      <td colSpan={5} className="px-4 pb-3 pt-0">
                        <ItemList items={g.items} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Stacked bar of a person's items by aging bucket, scaled to the busiest person. */
function StatusBar({ items, max }: { items: RequestSummary[]; max: number }) {
  const [hover, setHover] = useState<Bucket | null>(null);
  const counts = BUCKETS.map((b) => ({ ...b, n: items.filter((r) => bucketOf(r) === b.id).length })).filter((b) => b.n > 0);
  const summary = counts.map((b) => `${b.n} ${b.label.toLowerCase()}`).join(", ");
  return (
    <div className="flex items-center gap-3">
      <div className="relative flex h-2.5 flex-1 gap-[2px]" role="img" aria-label={summary}>
        {counts.map((b, i) => (
          <div
            key={b.id}
            className={cx("h-full transition-opacity", b.color, i === 0 && "rounded-l-[3px]", i === counts.length - 1 && "rounded-r-[3px]", hover && hover !== b.id && "opacity-40")}
            style={{ width: `${(b.n / max) * 100}%` }}
            onMouseEnter={() => setHover(b.id)}
            onMouseLeave={() => setHover(null)}
          />
        ))}
        {hover && (
          <div className="pointer-events-none absolute -top-8 left-0 z-10 whitespace-nowrap rounded bg-ink-900 px-2 py-1 text-2xs font-medium text-white shadow-pop">
            {counts.find((b) => b.id === hover)?.n} · {BUCKETS.find((b) => b.id === hover)?.label}
          </div>
        )}
      </div>
      <span className="w-6 text-right text-xs tabular-nums text-slate-500">{items.length}</span>
    </div>
  );
}

function ItemList({ items }: { items: RequestSummary[] }) {
  const sorted = [...items].sort((a, b) => b.overdue_days - a.overdue_days || (a.due_date ?? "9").localeCompare(b.due_date ?? "9"));
  return (
    <ul className="divide-y divide-slate-100 overflow-hidden rounded-md border border-slate-200 bg-white">
      {sorted.map((r) => (
        <li key={r.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-3 py-2 lg:grid-cols-[minmax(0,1fr)_7rem_10rem_8rem]">
          <Link to={`/requests/${r.id}`} className="min-w-0 truncate text-slate-900 hover:text-brand-700" onClick={(e) => e.stopPropagation()}>
            {r.external_id && <RefId className="mr-2">{r.external_id}</RefId>}
            {r.title}
            {r.owners.length > 1 && (
              <Badge tone="violet" className="ml-2">
                Shared
              </Badge>
            )}
          </Link>
          <Progress value={r.met} total={r.total} className="hidden lg:flex" />
          <span className="hidden lg:block">
            <StateBadge state={r.state} label={r.state_label} />
          </span>
          <span className={cx("text-right text-xs tabular-nums", r.overdue_days ? "font-semibold text-red-700" : "text-slate-600")}>
            {r.overdue_days ? `${r.overdue_days}d overdue` : r.due_date ? `Due ${fmtDate(r.due_date)}` : "No due date"}
          </span>
        </li>
      ))}
    </ul>
  );
}
