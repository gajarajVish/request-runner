import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate, fmtTime, type ImportBatch, type ImportRowView } from "../api";
import { ChecklistEditor, ChecklistView, toDraft, type DraftItem } from "../components/Checklist";
import { DraftEditor, OutboundView, mailStatusLabel, mailStatusTone } from "../components/Mail";
import { Avatar, Badge, Button, Card, Empty, ErrorText, Field, FlagList, Icon, Modal, PageHeader, RefId, Segmented, Spinner, Stat, cx, flagLabel, inputCls, th, type Tone } from "../components/ui";

const ACTION: Record<string, { tone: Tone; label: string }> = {
  new: { tone: "blue", label: "New" },
  changed: { tone: "amber", label: "Changed" },
  unchanged: { tone: "slate", label: "Unchanged" },
  duplicate: { tone: "slate", label: "Merged" },
  error: { tone: "red", label: "Error" },
  removed: { tone: "red", label: "Removed" },
};
const SUMMARY_LABEL: Record<string, string> = { duplicate: "Merged", blocked: "Held back" };
const STATUS: Record<string, { tone: Tone; label: string }> = {
  analyzing: { tone: "violet", label: "Analyzing" },
  review: { tone: "blue", label: "In review" },
  applied: { tone: "green", label: "Applied" },
  error: { tone: "red", label: "Error" },
  discarded: { tone: "slate", label: "Discarded" },
};
const ATTENTION = ["vague", "scope_failed", "past_due", "near_duplicate", "shared", "no_backup", "depends_on", "conflicting_id", "invalid", "closed_request"];

export function BatchPage() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["batch", id],
    queryFn: () => api.get<ImportBatch>(`/api/imports/batches/${id}`),
    refetchInterval: (query) => (query.state.data?.status === "analyzing" ? 1500 : false),
  });
  const [filter, setFilter] = useState<"all" | "attention" | "changes">("attention");
  const [edit, setEdit] = useState<ImportRowView | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const apply = useMutation({ mutationFn: () => api.post(`/api/imports/batches/${id}/apply`), onSuccess: () => qc.invalidateQueries() });
  const discard = useMutation({ mutationFn: () => api.post(`/api/imports/batches/${id}/discard`), onSuccess: () => qc.invalidateQueries() });
  const send = useMutation({ mutationFn: (ids?: number[]) => api.post(`/api/imports/batches/${id}/send`, { message_ids: ids ?? null }), onSuccess: () => qc.invalidateQueries() });
  const b = q.data;

  const rows = useMemo(() => {
    if (!b) return [];
    return b.rows.filter((r) => {
      if (filter === "attention") return r.action === "error" || r.action === "removed" || r.action === "changed" || r.flags.some((f) => ATTENTION.includes(f.code));
      if (filter === "changes") return r.action !== "unchanged";
      return true;
    });
  }, [b, filter]);

  if (q.isLoading) return null;
  if (!b) return <ErrorText error={q.error} />;
  const errors = b.rows.filter((r) => r.include && r.action === "error");
  const drafts = b.drafts.filter((m) => m.status === "draft");
  const current = b.drafts.find((m) => m.id === selected) ?? b.drafts[0];
  const st = STATUS[b.status] ?? { tone: "slate" as Tone, label: b.status };
  const attentionCount = b.rows.filter((r) => r.action === "error" || r.action === "removed" || r.action === "changed" || r.flags.some((f) => ATTENTION.includes(f.code))).length;

  return (
    <div>
      <PageHeader
        back={
          <Link to="/imports" className="mb-2 inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800">
            <Icon name="back" size={14} /> Imports
          </Link>
        }
        eyebrow="Import review"
        title={b.list?.name ?? b.filename}
        meta={
          <>
            <StateBadgeLike tone={st.tone} label={st.label} />
            <span className="inline-flex items-center gap-1.5">
              <Icon name="file" size={14} className="text-slate-400" />
              {b.filename}
            </span>
            <span className="tabular-nums text-slate-500">
              {b.applied_at ? `Applied ${fmtTime(b.applied_at)}` : `Uploaded ${fmtTime(b.created_at)}`}
            </span>
          </>
        }
        actions={
          b.status === "review" ? (
            <>
              <Button variant="ghost" onClick={() => discard.mutate()} busy={discard.isPending}>
                Discard import
              </Button>
              <Button variant="primary" disabled={errors.length > 0} onClick={() => apply.mutate()} busy={apply.isPending}>
                <Icon name="check" size={14} />
                Apply import
              </Button>
            </>
          ) : b.status === "applied" && drafts.length > 0 ? (
            <Button variant="primary" onClick={() => send.mutate(undefined)} busy={send.isPending}>
              <Icon name="send" size={14} />
              Send all {drafts.length} emails
            </Button>
          ) : null
        }
      />

      <div className="space-y-5">
        {Object.keys(b.summary).length > 0 && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {Object.entries(b.summary).map(([k, v]) => (
              <Stat
                key={k}
                label={SUMMARY_LABEL[k] ?? ACTION[k]?.label ?? k}
                value={v}
                tone={k === "blocked" || k === "error" || k === "removed" ? (v ? "danger" : "default") : k === "changed" && v ? "warning" : k === "new" ? "brand" : "default"}
              />
            ))}
          </div>
        )}

        {b.status === "analyzing" && (
          <Card>
            <div className="flex items-center gap-3 text-[13px] text-slate-700">
              <Spinner /> Reading the list and drafting a checklist for each row…
            </div>
          </Card>
        )}
        {b.errors.length > 0 && <FlagList flags={b.errors.map((e) => ({ code: "file", message: e, blocking: true }))} />}

        {b.status === "review" && (
          <div className={cx("flex items-start gap-2.5 rounded-md border px-4 py-3 text-[13px]", errors.length ? "border-red-200 bg-red-50 text-red-900" : "border-brand-200 bg-brand-50 text-brand-900")}>
            <Icon name={errors.length ? "alert" : "shield"} className="mt-0.5" />
            <div>
              Review each row's checklist. <b>Apply import</b> confirms them all; nothing is emailed until you press <b>Send all</b> on the next step.
              {errors.length > 0 && <p className="mt-1 font-medium">Fix or exclude {errors.length} row(s) with errors before applying.</p>}
              <ErrorText error={apply.error} />
            </div>
          </div>
        )}

        {b.status === "applied" && (
          <Card
            flush
            title={
              <span className="flex items-center gap-2">
                Outgoing emails
                <Badge>{b.drafts.length}</Badge>
                {drafts.length > 0 && <Badge tone="amber">{drafts.length} not sent</Badge>}
              </span>
            }
            actions={<span className="hidden text-xs text-slate-500 sm:inline">One email per person, covering every item they owe from this list.</span>}
          >
            {b.drafts.length === 0 ? (
              <p className="p-4 text-[13px] text-slate-600">Nothing new to send. Changes to items already sent go out as one change notice per person.</p>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
                <ul className="divide-y divide-slate-100 border-b border-slate-200 lg:border-b-0 lg:border-r" aria-label="Emails">
                  {b.drafts.map((m) => {
                    const active = current?.id === m.id;
                    return (
                      <li key={m.id}>
                        <button
                          onClick={() => setSelected(m.id)}
                          aria-current={active}
                          className={cx("flex w-full items-center gap-3 border-l-2 px-4 py-2.5 text-left", active ? "border-l-brand-600 bg-brand-50/60" : "border-l-transparent hover:bg-slate-50")}
                        >
                          <Avatar name={m.to[0] ?? "?"} />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[13px] font-medium text-slate-900">{m.to.join(", ")}</span>
                            <span className="block truncate text-xs tabular-nums text-slate-500">
                              {m.request_ids.length} item{m.request_ids.length === 1 ? "" : "s"}
                              {m.sent_at ? ` · sent ${fmtTime(m.sent_at)}` : ""}
                            </span>
                          </span>
                          <Badge tone={mailStatusTone(m.status)} dot>
                            {mailStatusLabel(m.status)}
                          </Badge>
                        </button>
                      </li>
                    );
                  })}
                </ul>
                <div className="min-w-0 bg-slate-50/50 p-4">
                  {current &&
                    (current.status === "draft" ? (
                      <DraftEditor key={current.id} m={current} onSend={() => send.mutate([current.id])} sendLabel="Send this email" busy={send.isPending} />
                    ) : (
                      <OutboundView key={current.id} m={current} />
                    ))}
                  <ErrorText error={send.error} />
                </div>
              </div>
            )}
          </Card>
        )}

        {b.rows.length > 0 && (
          <Card
            flush
            title={
              <span className="flex items-center gap-2">
                Rows <Badge>{b.rows.length}</Badge>
              </span>
            }
            actions={
              <Segmented
                label="Filter rows"
                value={filter}
                onChange={setFilter}
                options={[
                  { id: "attention", label: `Needs a look · ${attentionCount}` },
                  { id: "changes", label: "Changes" },
                  { id: "all", label: "All" },
                ]}
              />
            }
          >
            {rows.length === 0 ? (
              <div className="p-4">
                <Empty icon="check">Nothing needs a look. Switch to “All” to see every row.</Empty>
              </div>
            ) : (
              <div>
                <div className="hidden border-b border-slate-200 bg-slate-50 md:grid md:grid-cols-[4.5rem_6rem_minmax(0,1fr)_11rem_7.5rem_8.5rem]">
                  <span className={th}>ID</span>
                  <span className={th}>Action</span>
                  <span className={th}>Request</span>
                  <span className={th}>Owner</span>
                  <span className={th}>Due</span>
                  <span className={cx(th, "text-right")}>
                    <span className="sr-only">Row actions</span>
                  </span>
                </div>
                <div className="divide-y divide-slate-100">
                  {rows.map((r) => (
                    <RowView key={r.id} r={r} editable={b.status === "review"} onEdit={() => setEdit(r)} batchId={b.id} />
                  ))}
                </div>
              </div>
            )}
          </Card>
        )}
      </div>
      <RowEditor batch={b} row={edit} onClose={() => setEdit(null)} />
    </div>
  );
}

function StateBadgeLike({ tone, label }: { tone: Tone; label: string }) {
  return (
    <Badge tone={tone} dot>
      {label}
    </Badge>
  );
}

function RowView({ r, editable, onEdit, batchId }: { r: ImportRowView; editable: boolean; onEdit: () => void; batchId: number }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const toggle = useMutation({ mutationFn: () => api.patch(`/api/imports/batches/${batchId}/rows/${r.id}`, { include: !r.include }), onSuccess: () => qc.invalidateQueries({ queryKey: ["batch", batchId] }) });
  const items = r.scope?.items ?? [];
  const flags = r.flags.filter((f) => f.code !== "duplicate" || r.action !== "duplicate");
  const showItems = items.length > 0 && r.action !== "unchanged" && r.action !== "duplicate";
  const hasDetail = showItems || r.changes.length > 0 || flags.length > 0 || !!r.instructions;
  const lead = flags.find((f) => f.blocking) ?? flags[0];
  return (
    <div className={cx(!r.include && "bg-slate-50/70")}>
      <div className={cx("grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 px-4 py-2.5 md:grid-cols-[4.5rem_6rem_minmax(0,1fr)_11rem_7.5rem_8.5rem] md:items-center md:gap-0 md:px-0", !r.include && "opacity-60")}>
        <div className="md:px-4">
          <RefId>{r.external_id}</RefId>
        </div>
        <div className="flex flex-wrap items-center gap-1 md:px-4">
          <Badge tone={ACTION[r.action].tone}>{ACTION[r.action].label}</Badge>
          {r.blocked && <Badge tone="red">Held back</Badge>}
          {!r.include && <Badge>Excluded</Badge>}
        </div>
        <div className="col-span-2 min-w-0 md:col-span-1 md:px-4">
          <button onClick={() => hasDetail && setOpen(!open)} aria-expanded={open} className={cx("flex w-full min-w-0 items-start gap-1.5 text-left", hasDetail && "group")}>
            {hasDetail && <Icon name="chevronRight" size={14} className={cx("mt-0.5 text-slate-400 transition-transform group-hover:text-slate-700", open && "rotate-90")} />}
            <span className="min-w-0">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-[13px] font-medium text-slate-900">{r.title}</span>
                {r.merged_into && <span className="text-xs text-slate-500">→ merged into {r.merged_into}</span>}
                {Object.keys(r.edits).length > 0 && <Badge>Edited</Badge>}
                {flags.map((f) => (
                  <Badge key={f.code} tone={f.blocking || f.code === "vague" ? "red" : "amber"} title={f.message}>
                    {flagLabel(f.code)}
                  </Badge>
                ))}
              </span>
              {lead && !open && <span className={cx("mt-0.5 block truncate text-xs", lead.blocking ? "text-red-700" : "text-amber-800")}>{lead.message}</span>}
            </span>
          </button>
        </div>
        <div className="col-span-2 truncate text-xs text-slate-600 md:col-span-1 md:px-4 md:text-[13px]">
          {r.action !== "removed" && (
            <>
              {r.owners.map((o) => o.name || o.email).join(r.ownership_mode === "all" ? " and " : " or ")}
              <span className="md:hidden">{r.due_date && ` · due ${fmtDate(r.due_date)}`}</span>
            </>
          )}
        </div>
        <div className={cx("hidden whitespace-nowrap tabular-nums md:block md:px-4", r.flags.some((f) => f.code === "past_due") ? "font-medium text-red-700" : "text-slate-600")}>{r.due_date ? fmtDate(r.due_date) : "—"}</div>
        <div className="col-span-2 flex gap-1.5 md:col-span-1 md:justify-end md:px-4">
          {editable && r.action !== "unchanged" && (
            <>
              {r.action !== "removed" && (
                <Button size="sm" onClick={onEdit}>
                  {r.action === "error" ? "Resolve" : "Edit"}
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => toggle.mutate()} busy={toggle.isPending}>
                {r.include ? "Exclude" : "Include"}
              </Button>
            </>
          )}
          {r.request_id && (
            <Link to={`/requests/${r.request_id}`} className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-brand-700 hover:bg-brand-50">
              Open <Icon name="chevronRight" size={12} />
            </Link>
          )}
        </div>
      </div>
      {open && hasDetail && (
        <div className="space-y-3 border-t border-slate-100 bg-slate-50/70 px-4 py-3 md:pl-[10.5rem]">
          {r.instructions && (
            <div>
              <p className="text-2xs font-semibold uppercase tracking-[0.06em] text-slate-500">Instructions</p>
              <p className="mt-0.5 text-[13px] text-slate-700">{r.instructions}</p>
            </div>
          )}
          {r.action !== "removed" && (r.owners.length > 1 || r.backup_email) && (
            <p className="text-xs text-slate-600">
              {r.owners.length > 1 && (r.ownership_mode === "all" ? "Shared: both must respond." : "Shared: either owner can satisfy it.")}
              {r.backup_email && ` Backup: ${r.backup_email}.`}
            </p>
          )}
          {r.changes.length > 0 && (
            <div>
              <p className="text-2xs font-semibold uppercase tracking-[0.06em] text-slate-500">Changes since last import</p>
              <ul className="mt-1 space-y-0.5 text-xs">
                {r.changes.map((c) => (
                  <li key={c.field}>
                    <span className="font-medium text-slate-700">{c.field.replace("_", " ")}:</span> <span className="text-red-700 line-through">{fmt(c.old)}</span> → <span className="text-emerald-700">{fmt(c.new)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <FlagList flags={flags} />
          {showItems && (
            <div className="rounded-md border border-slate-200 bg-white p-3">
              <p className="mb-2 text-2xs font-semibold uppercase tracking-[0.06em] text-slate-500">Drafted checklist</p>
              <ChecklistView items={items.map((it, i) => ({ ...it, key: `i${i}` }))} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function fmt(v: unknown) {
  if (v === null || v === undefined || v === "") return "none";
  return Array.isArray(v) ? v.join(", ") : String(v);
}

function RowEditor({ batch, row, onClose }: { batch: ImportBatch; row: ImportRowView | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [items, setItems] = useState<DraftItem[]>([]);
  const [instructions, setInstructions] = useState("");
  const [due, setDue] = useState("");
  const [mode, setMode] = useState<"any" | "all">("any");
  const [merge, setMerge] = useState("");
  const [loadedFor, setLoadedFor] = useState<number | null>(null);
  if (row && loadedFor !== row.id) {
    setLoadedFor(row.id);
    setItems(toDraft((row.scope?.items ?? []) as any));
    setInstructions(row.instructions ?? "");
    setDue(row.due_date ?? "");
    setMode(row.ownership_mode);
    setMerge(row.flags.find((f) => f.code === "near_duplicate")?.other as string ?? "");
  }
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch(`/api/imports/batches/${batch.id}/rows/${row!.id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["batch", batch.id] });
      setLoadedFor(null);
      onClose();
    },
  });
  if (!row) return null;
  const merged = row.action === "duplicate";
  const targets = batch.rows.filter((r) => r.id !== row.id && ["new", "changed", "unchanged"].includes(r.action));
  return (
    <Modal open={!!row} onClose={() => { setLoadedFor(null); onClose(); }} title={`${row.external_id} · ${row.title}`} wide>
      <div className="space-y-5">
        <FlagList flags={row.flags} />
        <div className="grid gap-3 sm:grid-cols-[2fr_1fr_1fr]">
          <Field label="Instructions" hint="Changing them asks the agent to redraft this row's checklist.">
            <textarea className={cx(inputCls, "min-h-[70px]")} value={instructions} onChange={(e) => setInstructions(e.target.value)} />
          </Field>
          <Field label="Due date">
            <input type="date" className={inputCls} value={due} onChange={(e) => setDue(e.target.value)} />
          </Field>
          {row.owners.length > 1 ? (
            <Field label="Shared item">
              <select className={inputCls} value={mode} onChange={(e) => setMode(e.target.value as "any" | "all")}>
                <option value="any">Either owner can satisfy it</option>
                <option value="all">Both must respond</option>
              </select>
            </Field>
          ) : (
            <div />
          )}
        </div>
        <div>
          <p className="mb-2 text-2xs font-semibold uppercase tracking-[0.06em] text-slate-500">Checklist</p>
          <ChecklistEditor items={items} onChange={setItems} />
        </div>
        {row.action === "new" && (
          <Field label="Merge into another row" hint={merged ? `Currently merged into ${row.merged_into}.` : "Use this when two ids are really the same request. The id is kept as an alias."}>
            <select className={inputCls} value={merge} onChange={(e) => setMerge(e.target.value)}>
              <option value="">Don't merge</option>
              {targets.map((t) => (
                <option key={t.id} value={t.external_id}>
                  {t.external_id} · {t.title}
                </option>
              ))}
            </select>
          </Field>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => { setLoadedFor(null); onClose(); }}>
            Cancel
          </Button>
          <Button
            variant="primary"
            busy={save.isPending}
            onClick={() => {
              const body: Record<string, unknown> = {};
              if (instructions.trim() && instructions !== row.instructions) body.instructions = instructions;
              else if (JSON.stringify(items) !== JSON.stringify(toDraft((row.scope?.items ?? []) as any))) body.items = items;
              if (due && due !== row.due_date) body.due_date = due;
              if (mode !== row.ownership_mode) body.ownership_mode = mode;
              if (row.action === "new" && (merge || "") !== (row.merged_into || "") && (merge || row.merged_into)) body.merge_into = merge;
              if (Object.keys(body).length === 0) return onClose();
              save.mutate(body);
            }}
          >
            Save row
          </Button>
        </div>
        <ErrorText error={save.error} />
      </div>
    </Modal>
  );
}
