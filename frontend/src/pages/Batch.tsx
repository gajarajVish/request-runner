import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate, type ImportBatch, type ImportRowView } from "../api";
import { ChecklistEditor, ChecklistView, toDraft, type DraftItem } from "../components/Checklist";
import { DraftEditor, OutboundView } from "../components/Mail";
import { Badge, Button, Card, Empty, ErrorText, Field, FlagList, Modal, Spinner, cx, inputCls, type Tone } from "../components/ui";

const ACTION: Record<string, { tone: Tone; label: string }> = {
  new: { tone: "blue", label: "new" },
  changed: { tone: "amber", label: "changed" },
  unchanged: { tone: "slate", label: "unchanged" },
  duplicate: { tone: "slate", label: "merged" },
  error: { tone: "red", label: "error" },
  removed: { tone: "red", label: "removed" },
};

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
  const apply = useMutation({ mutationFn: () => api.post(`/api/imports/batches/${id}/apply`), onSuccess: () => qc.invalidateQueries() });
  const discard = useMutation({ mutationFn: () => api.post(`/api/imports/batches/${id}/discard`), onSuccess: () => qc.invalidateQueries() });
  const send = useMutation({ mutationFn: (ids?: number[]) => api.post(`/api/imports/batches/${id}/send`, { message_ids: ids ?? null }), onSuccess: () => qc.invalidateQueries() });
  const b = q.data;

  const rows = useMemo(() => {
    if (!b) return [];
    return b.rows.filter((r) => {
      if (filter === "attention") return r.action === "error" || r.action === "removed" || r.action === "changed" || r.flags.some((f) => ["vague", "scope_failed", "past_due", "near_duplicate", "shared", "no_backup", "depends_on", "conflicting_id", "invalid", "closed_request"].includes(f.code));
      if (filter === "changes") return r.action !== "unchanged";
      return true;
    });
  }, [b, filter]);

  if (q.isLoading) return null;
  if (!b) return <ErrorText error={q.error} />;
  const errors = b.rows.filter((r) => r.include && r.action === "error");
  const drafts = b.drafts.filter((m) => m.status === "draft");

  return (
    <div className="space-y-5">
      <div>
        <Link to="/imports" className="text-xs text-slate-500 hover:text-slate-700">
          ← Imports
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold">{b.list?.name}</h1>
          <span className="text-sm text-slate-500">{b.filename}</span>
          <Badge tone={b.status === "applied" ? "green" : b.status === "review" ? "blue" : b.status === "error" ? "red" : "slate"}>{b.status}</Badge>
        </div>
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          {Object.entries(b.summary).map(([k, v]) => (
            <Badge key={k} tone={ACTION[k]?.tone ?? (k === "blocked" ? "red" : "slate")}>
              {v} {ACTION[k]?.label ?? k}
            </Badge>
          ))}
        </div>
      </div>

      {b.status === "analyzing" && (
        <Card>
          <div className="flex items-center gap-3 text-sm text-slate-600">
            <Spinner /> Reading the list and drafting a checklist for each row…
          </div>
        </Card>
      )}
      {b.errors.length > 0 && <FlagList flags={b.errors.map((e) => ({ code: "file", message: e, blocking: true }))} />}

      {b.status === "review" && (
        <Card>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex-1 text-sm text-slate-600">
              Review each row's checklist. Applying confirms them all; nothing is emailed until you press <b>Send all</b> on the next step.
              {errors.length > 0 && <p className="mt-1 text-red-700">Fix or exclude {errors.length} row(s) with errors first.</p>}
            </div>
            <Button variant="ghost" onClick={() => discard.mutate()} busy={discard.isPending}>
              Discard
            </Button>
            <Button variant="primary" disabled={errors.length > 0} onClick={() => apply.mutate()} busy={apply.isPending}>
              Apply import
            </Button>
          </div>
          <ErrorText error={apply.error} />
        </Card>
      )}

      {b.status === "applied" && (
        <Card
          title={`Emails to send (${drafts.length} draft${drafts.length === 1 ? "" : "s"})`}
          actions={
            drafts.length > 0 && (
              <Button variant="primary" onClick={() => send.mutate(undefined)} busy={send.isPending}>
                Send all {drafts.length}
              </Button>
            )
          }
        >
          {b.drafts.length === 0 ? (
            <p className="text-sm text-slate-500">Nothing new to send. Changes to items already sent go out as one change notice per person.</p>
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-slate-500">One email per person, covering every item they owe from this list. Shared items appear in each owner's email.</p>
              {b.drafts.map((m) =>
                m.status === "draft" ? (
                  <DraftEditor key={m.id} m={m} onSend={() => send.mutate([m.id])} sendLabel="Send this one" busy={send.isPending} />
                ) : (
                  <OutboundView key={m.id} m={m} compact />
                ),
              )}
            </div>
          )}
          <ErrorText error={send.error} />
        </Card>
      )}

      {b.rows.length > 0 && (
        <Card
          title="Rows"
          actions={
            <div className="flex rounded-md border border-slate-300 p-0.5 text-xs">
              {(["attention", "changes", "all"] as const).map((f) => (
                <button key={f} onClick={() => setFilter(f)} className={cx("rounded px-2 py-0.5", filter === f ? "bg-slate-800 text-white" : "text-slate-600")}>
                  {f === "attention" ? "Needs a look" : f === "changes" ? "Changes" : "All"}
                </button>
              ))}
            </div>
          }
        >
          {rows.length === 0 ? (
            <Empty>Nothing needs a look. Switch to “All” to see every row.</Empty>
          ) : (
            <div className="divide-y divide-slate-100">
              {rows.map((r) => (
                <RowView key={r.id} r={r} editable={b.status === "review"} onEdit={() => setEdit(r)} batchId={b.id} />
              ))}
            </div>
          )}
        </Card>
      )}
      <RowEditor batch={b} row={edit} onClose={() => setEdit(null)} />
    </div>
  );
}

function RowView({ r, editable, onEdit, batchId }: { r: ImportRowView; editable: boolean; onEdit: () => void; batchId: number }) {
  const qc = useQueryClient();
  const toggle = useMutation({ mutationFn: () => api.patch(`/api/imports/batches/${batchId}/rows/${r.id}`, { include: !r.include }), onSuccess: () => qc.invalidateQueries({ queryKey: ["batch", batchId] }) });
  const items = r.scope?.items ?? [];
  return (
    <div className={cx("py-3", !r.include && "opacity-50")}>
      <div className="flex flex-wrap items-start gap-3">
        <span className="w-14 shrink-0 font-mono text-xs font-semibold text-slate-500">{r.external_id}</span>
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={ACTION[r.action].tone}>{ACTION[r.action].label}</Badge>
            {r.blocked && <Badge tone="red">held back</Badge>}
            {!r.include && <Badge>excluded</Badge>}
            <span className="font-medium text-slate-800">{r.title}</span>
            {r.merged_into && <span className="text-xs text-slate-500">→ {r.merged_into}</span>}
            {r.request_id && (
              <Link to={`/requests/${r.request_id}`} className="text-xs text-brand-700 hover:underline">
                open
              </Link>
            )}
          </div>
          {r.instructions && <p className="text-xs text-slate-600">{r.instructions}</p>}
          {r.action !== "removed" && (
            <p className="text-xs text-slate-500">
              {r.owners.map((o) => o.name || o.email).join(r.ownership_mode === "all" ? " and " : " or ")}
              {r.owners.length > 1 && ` (${r.ownership_mode === "all" ? "both must respond" : "either can satisfy"})`}
              {r.due_date && ` · due ${fmtDate(r.due_date)}`}
              {r.backup_email && ` · backup ${r.backup_email}`}
              {Object.keys(r.edits).length > 0 && <Badge className="ml-2">edited</Badge>}
            </p>
          )}
          {r.changes.length > 0 && (
            <ul className="text-xs">
              {r.changes.map((c) => (
                <li key={c.field}>
                  <span className="font-medium">{c.field.replace("_", " ")}:</span> <span className="text-red-700 line-through">{fmt(c.old)}</span> → <span className="text-emerald-700">{fmt(c.new)}</span>
                </li>
              ))}
            </ul>
          )}
          <FlagList flags={r.flags.filter((f) => f.code !== "duplicate" || r.action !== "duplicate")} />
          {items.length > 0 && r.action !== "unchanged" && r.action !== "duplicate" && (
            <div className="rounded-md bg-slate-50 p-2">
              <ChecklistView items={items.map((it, i) => ({ ...it, key: `i${i}` }))} />
            </div>
          )}
        </div>
        {editable && r.action !== "unchanged" && (
          <div className="flex shrink-0 gap-1.5">
            {r.action !== "removed" && r.action !== "error" && (
              <Button size="sm" onClick={onEdit}>
                Edit
              </Button>
            )}
            {r.action === "error" && (
              <Button size="sm" onClick={onEdit}>
                Resolve
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => toggle.mutate()} busy={toggle.isPending}>
              {r.include ? "Exclude" : "Include"}
            </Button>
          </div>
        )}
      </div>
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
          <p className="mb-2 text-sm font-medium text-slate-700">Checklist</p>
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
