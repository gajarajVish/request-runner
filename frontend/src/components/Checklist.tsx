import { useState } from "react";
import type { Citation, EvidenceFile, Item, Subpoint, Verdict } from "../api";
import { Badge, Button, Disclosure, VERDICT, VerdictBadge, cx, inputCls } from "./ui";

// --------------------------------------------------------------------------- read-only view

export function criteriaLines(c: Record<string, any>): string[] {
  const out: string[] = [];
  if (c.period) out.push(`Period: ${c.period}`);
  if (c.entity) out.push(`Entity: ${c.entity}`);
  if (c.format) out.push(`Format: ${c.format}`);
  for (const e of c.required_elements ?? []) out.push(`Shows: ${e}`);
  if (c.signature?.required) {
    const s = c.signature;
    out.push(s.mode === "named_parties" && s.parties?.length ? `Signed by ${s.parties.join(" and ")}${s.date_required ? ", dated" : ""}` : `Signed${s.date_required ? " and dated" : ""}`);
  }
  if (c.currency_rule) out.push(`Current: ${c.currency_rule}`);
  return out;
}

export function ChecklistView({ items, files, onOverride }: { items: Item[]; files?: EvidenceFile[]; onOverride?: (item: Item) => void }) {
  return (
    <ol className="space-y-3">
      {items.map((it, n) => (
        <ItemRow key={it.key} n={n + 1} item={it} files={files} onOverride={onOverride} />
      ))}
    </ol>
  );
}

function ItemRow({ n, item, files, onOverride }: { n: number; item: Item; files?: EvidenceFile[]; onOverride?: (item: Item) => void }) {
  const v = item.verdict;
  const crit = criteriaLines(item.criteria);
  const tone = v ? VERDICT[v.verdict]?.tone : undefined;
  return (
    <li className={cx("rounded-md border p-3", tone === "green" ? "border-emerald-200 bg-emerald-50/40" : tone === "red" ? "border-red-200" : tone === "amber" ? "border-amber-200" : "border-slate-200")}>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 w-5 shrink-0 text-right text-xs font-semibold text-slate-400">{n}.</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="text-sm font-medium text-slate-800">
              {item.description}
              {item.kind === "answer" && (
                <Badge tone="violet" className="ml-2 align-middle">
                  answer
                </Badge>
              )}
            </p>
            {v && (
              <div className="flex items-center gap-1.5">
                {v.source === "requester_override" && <Badge tone="slate" title={v.override_reason}>overridden</Badge>}
                <VerdictBadge verdict={v.verdict} />
              </div>
            )}
          </div>
          {crit.length > 0 && <p className="mt-1 text-xs text-slate-500">{crit.join(" · ")}</p>}
          {item.subpoints.length > 0 && !v && (
            <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-xs text-slate-600">
              {item.subpoints.map((sp) => (
                <li key={sp.key}>
                  {sp.text}
                  {sp.condition && <span className="text-slate-400"> ({sp.condition})</span>}
                </li>
              ))}
            </ul>
          )}
          {v && v.verdict !== "pending" && <VerdictDetail item={item} v={v} files={files} />}
          {v && onOverride && v.verdict !== "pending" && (
            <button onClick={() => onOverride(item)} className="mt-2 text-xs text-slate-500 underline-offset-2 hover:text-slate-700 hover:underline">
              Override verdict…
            </button>
          )}
        </div>
      </div>
    </li>
  );
}

function VerdictDetail({ item, v, files }: { item: Item; v: Verdict; files?: EvidenceFile[] }) {
  const cites = v.citations ?? [];
  return (
    <div className="mt-2 space-y-2">
      {v.rationale && <p className="text-xs text-slate-600">{v.rationale}</p>}
      {v.source === "requester_override" && v.override_reason && <p className="text-xs text-slate-600">Override reason: {v.override_reason}</p>}
      {v.missing?.length > 0 && v.verdict !== "met" && (
        <ul className="space-y-0.5 text-xs text-red-700">
          {v.missing.map((m, i) => (
            <li key={i}>• {m}</li>
          ))}
        </ul>
      )}
      {v.review_flags?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {v.review_flags.map((f) => (
            <Badge key={f} tone="amber">
              review: {f.replace(/_/g, " ")}
            </Badge>
          ))}
        </div>
      )}
      {item.subpoints.length > 0 && (
        <ul className="space-y-1.5">
          {item.subpoints.map((sp) => {
            const sv = v.subpoints?.find((x) => x.key === sp.key);
            return (
              <li key={sp.key} className="rounded bg-slate-50 px-2 py-1.5 text-xs">
                <div className="flex items-start justify-between gap-2">
                  <span>
                    {sp.text}
                    {sp.condition && <span className="text-slate-400"> ({sp.condition})</span>}
                  </span>
                  <VerdictBadge verdict={sv?.verdict ?? "pending"} />
                </div>
                {sv?.note && <p className="mt-0.5 text-slate-500">{sv.note}</p>}
                {sv?.citations?.map((c, i) => <CitationView key={i} c={c} files={files} />)}
              </li>
            );
          })}
        </ul>
      )}
      {cites.length > 0 && (
        <Disclosure summary={`${cites.length} citation${cites.length > 1 ? "s" : ""}`} defaultOpen={v.verdict !== "met"}>
          <div className="space-y-1.5">
            {cites.map((c, i) => (
              <CitationView key={i} c={c} files={files} />
            ))}
          </div>
        </Disclosure>
      )}
    </div>
  );
}

export function CitationView({ c, files }: { c: Citation; files?: EvidenceFile[] }) {
  const f = files?.find((x) => x.id === c.file_id);
  const img = f?.images.find((im) => im.label === c.location);
  const [zoom, setZoom] = useState(false);
  return (
    <div className={cx("mt-1 rounded border px-2 py-1.5 text-xs", c.problem ? "border-red-200 bg-red-50/50" : "border-slate-200 bg-white")}>
      <div className="flex flex-wrap items-center gap-1.5">
        {c.file_id ? (
          <a className="font-medium text-brand-700 hover:underline" href={`/api/files/${c.file_id}/download`}>
            {c.filename}
          </a>
        ) : (
          <span className="font-medium">{c.filename ?? c.evidence_id}</span>
        )}
        {c.location && <span className="text-slate-500">{c.location}</span>}
        {c.verified ? (
          <Badge tone="green" title="The quote was found at this location in the extracted text">
            quote verified
          </Badge>
        ) : c.visual && !c.problem ? (
          <Badge tone="blue" title="Based on the page image, not on quoted text">
            visual evidence
          </Badge>
        ) : (
          <Badge tone="red">{c.problem ?? "unverified"}</Badge>
        )}
      </div>
      {c.quote && <blockquote className="mt-1 border-l-2 border-slate-300 pl-2 text-slate-700">“{c.quote}”</blockquote>}
      {c.note && <p className="mt-1 text-slate-500">{c.note}</p>}
      {img && (
        <button onClick={() => setZoom(!zoom)} className="mt-1.5 block">
          <img src={`/api/files/${f!.id}/images/${img.index}`} alt={`${f!.filename} ${img.label}`} className={cx("rounded border border-slate-200", zoom ? "max-w-full" : "max-h-40")} />
        </button>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- editor

export type DraftItem = { kind: "document" | "answer"; description: string; criteria: Record<string, any>; subpoints: Subpoint[] };

export const emptyCriteria = () => ({ period: null, entity: null, format: null, required_elements: [], signature: null, currency_rule: null });

export function toDraft(items: { kind: string; description: string; criteria: Record<string, any>; subpoints: Subpoint[] }[]): DraftItem[] {
  return items.map((i) => ({
    kind: i.kind as DraftItem["kind"],
    description: i.description,
    criteria: { ...emptyCriteria(), ...i.criteria },
    subpoints: (i.subpoints ?? []).map((s) => ({ key: s.key, text: s.text, condition: s.condition ?? null })),
  }));
}

export function ChecklistEditor({ items, onChange }: { items: DraftItem[]; onChange: (items: DraftItem[]) => void }) {
  const set = (i: number, patch: Partial<DraftItem>) => onChange(items.map((it, n) => (n === i ? { ...it, ...patch } : it)));
  const setCrit = (i: number, patch: Record<string, any>) => set(i, { criteria: { ...items[i].criteria, ...patch } });
  return (
    <div className="space-y-3">
      {items.map((it, i) => (
        <div key={i} className="rounded-md border border-slate-200 bg-slate-50/60 p-3">
          <div className="flex items-start gap-2">
            <span className="mt-2 w-5 text-right text-xs font-semibold text-slate-400">{i + 1}.</span>
            <div className="flex-1 space-y-2">
              <div className="flex gap-2">
                <select className={cx(inputCls, "w-32")} value={it.kind} onChange={(e) => set(i, { kind: e.target.value as DraftItem["kind"] })}>
                  <option value="document">Document</option>
                  <option value="answer">Answer</option>
                </select>
                <textarea className={cx(inputCls, "min-h-[38px]")} rows={1} value={it.description} onChange={(e) => set(i, { description: e.target.value })} placeholder="What the provider should send" />
                <Button variant="ghost" size="sm" onClick={() => onChange(items.filter((_, n) => n !== i))} title="Remove item">
                  ✕
                </Button>
              </div>
              <Disclosure summary="Acceptance criteria and sub-points">
                <div className="grid gap-2 sm:grid-cols-2">
                  {(["period", "entity", "format", "currency_rule"] as const).map((k) => (
                    <input key={k} className={inputCls} placeholder={k.replace("_", " ")} value={it.criteria[k] ?? ""} onChange={(e) => setCrit(i, { [k]: e.target.value || null })} />
                  ))}
                  <input
                    className={cx(inputCls, "sm:col-span-2")}
                    placeholder="Must show (comma separated)"
                    value={(it.criteria.required_elements ?? []).join(", ")}
                    onChange={(e) => setCrit(i, { required_elements: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                  />
                  <div className="flex flex-wrap items-center gap-3 text-xs sm:col-span-2">
                    <label className="flex items-center gap-1.5">
                      <input type="checkbox" checked={!!it.criteria.signature?.required} onChange={(e) => setCrit(i, { signature: e.target.checked ? { required: true, mode: "present", parties: [], date_required: false } : null })} />
                      Signature required
                    </label>
                    {it.criteria.signature?.required && (
                      <>
                        <select className={cx(inputCls, "w-auto py-1 text-xs")} value={it.criteria.signature.mode} onChange={(e) => setCrit(i, { signature: { ...it.criteria.signature, mode: e.target.value } })}>
                          <option value="present">any clear signature</option>
                          <option value="named_parties">signed by named parties</option>
                        </select>
                        {it.criteria.signature.mode === "named_parties" && (
                          <input className={cx(inputCls, "w-64 py-1 text-xs")} placeholder="Parties (comma separated)" value={(it.criteria.signature.parties ?? []).join(", ")} onChange={(e) => setCrit(i, { signature: { ...it.criteria.signature, parties: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } })} />
                        )}
                        <label className="flex items-center gap-1.5">
                          <input type="checkbox" checked={!!it.criteria.signature.date_required} onChange={(e) => setCrit(i, { signature: { ...it.criteria.signature, date_required: e.target.checked } })} />
                          dated
                        </label>
                      </>
                    )}
                  </div>
                </div>
                <div className="mt-3 space-y-1.5">
                  <p className="text-xs font-medium text-slate-600">Required sub-points {it.kind === "answer" ? "(each must be answered)" : ""}</p>
                  {it.subpoints.map((sp, j) => (
                    <div key={j} className="flex gap-2">
                      <input className={inputCls} value={sp.text} placeholder="What the answer must state" onChange={(e) => set(i, { subpoints: it.subpoints.map((x, m) => (m === j ? { ...x, text: e.target.value } : x)) })} />
                      <input className={cx(inputCls, "w-56")} value={sp.condition ?? ""} placeholder="Only if… (optional)" onChange={(e) => set(i, { subpoints: it.subpoints.map((x, m) => (m === j ? { ...x, condition: e.target.value || null } : x)) })} />
                      <Button variant="ghost" size="sm" onClick={() => set(i, { subpoints: it.subpoints.filter((_, m) => m !== j) })}>
                        ✕
                      </Button>
                    </div>
                  ))}
                  <Button size="sm" variant="ghost" onClick={() => set(i, { subpoints: [...it.subpoints, { key: String.fromCharCode(97 + it.subpoints.length), text: "", condition: null }] })}>
                    + sub-point
                  </Button>
                </div>
              </Disclosure>
            </div>
          </div>
        </div>
      ))}
      <Button size="sm" onClick={() => onChange([...items, { kind: "document", description: "", criteria: emptyCriteria(), subpoints: [] }])}>
        + Add item
      </Button>
    </div>
  );
}
