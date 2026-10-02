import { Fragment, useState } from "react";
import type { Citation, EvidenceFile, Item, Subpoint, Verdict } from "../api";
import { Badge, Button, Disclosure, Icon, VerdictBadge, cx, inputCls } from "./ui";

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

export function criteriaFields(c: Record<string, any>): [string, string][] {
  const out: [string, string][] = [];
  if (c.period) out.push(["Period", c.period]);
  if (c.entity) out.push(["Entity", c.entity]);
  if (c.format) out.push(["Format", c.format]);
  if (c.signature?.required) {
    const s = c.signature;
    out.push(["Signature", s.mode === "named_parties" && s.parties?.length ? `Signed by ${s.parties.join(" and ")}${s.date_required ? ", dated" : ""}` : `Signed${s.date_required ? " and dated" : ""}`]);
  }
  if (c.currency_rule) out.push(["Currency", c.currency_rule]);
  return out;
}

export function ChecklistView({ items, files, onOverride }: { items: Item[]; files?: EvidenceFile[]; onOverride?: (item: Item) => void }) {
  return (
    <ol className="divide-y divide-slate-200">
      {items.map((it, n) => (
        <ItemRow key={it.key} n={n + 1} item={it} files={files} onOverride={onOverride} />
      ))}
    </ol>
  );
}

const MARK: Record<string, { icon: "check" | "x" | "alert" | "clock"; cls: string }> = {
  met: { icon: "check", cls: "bg-emerald-600 text-white" },
  partly_met: { icon: "alert", cls: "bg-amber-500 text-white" },
  not_met: { icon: "x", cls: "bg-red-600 text-white" },
  unreadable: { icon: "alert", cls: "bg-violet-600 text-white" },
};

function ItemRow({ n, item, files, onOverride }: { n: number; item: Item; files?: EvidenceFile[]; onOverride?: (item: Item) => void }) {
  const v = item.verdict;
  const crit = criteriaFields(item.criteria);
  const must = (item.criteria.required_elements as string[] | undefined) ?? [];
  const judged = v && v.verdict !== "pending";
  const mark = judged ? MARK[v.verdict] : undefined;
  const sources = judged && v.verdict === "met" ? [...new Set((v.citations ?? []).map((c) => c.filename).filter(Boolean))] : [];
  const [open, setOpen] = useState(false);
  return (
    <li className="py-3">
      <div className="flex items-start gap-3">
        <span className={cx("mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full", mark ? mark.cls : "border-2 border-slate-300 text-[10px] font-semibold text-slate-500")} aria-hidden>
          {mark ? <Icon name={mark.icon} size={12} /> : n}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
            <p className="min-w-0 flex-1 text-[13.5px] font-medium leading-snug text-slate-900">{item.description}</p>
            <div className="flex items-center gap-1.5">
              {v?.source === "requester_override" && <Badge tone="blue" title={v.override_reason}>Overridden</Badge>}
              {v ? <VerdictBadge verdict={v.verdict} /> : item.kind === "answer" && <Badge>Answer</Badge>}
            </div>
          </div>
          {judged && v.verdict !== "met" && v.missing?.[0] && <p className="mt-1 text-[13px] text-red-800">Still needed: {v.missing.join(" ")}</p>}
          {sources.length > 0 && (
            <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-600">
              <Icon name="file" size={13} className="text-slate-500" />
              {sources.join(", ")}
            </p>
          )}
          {!v && (crit.length > 0 || must.length > 0 || item.subpoints.length > 0) && (
            <p className="mt-1 text-xs text-slate-600">
              {[...crit.map(([k, val]) => `${k}: ${val}`), ...(must.length ? [`Must show: ${must.join("; ")}`] : []), ...item.subpoints.map((sp) => sp.text)].join(" · ")}
            </p>
          )}
          {(judged || onOverride) && (
            <button onClick={() => setOpen(!open)} aria-expanded={open} className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800">
              <Icon name="chevronRight" size={12} className={cx("transition-transform", open && "rotate-90")} />
              {open ? "Hide details" : "Details"}
            </button>
          )}
          {open && (
            <div className="mt-2 space-y-2 rounded-md border border-slate-200 bg-slate-50/60 p-3">
              {(crit.length > 0 || must.length > 0) && (
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
                  {crit.map(([k, val]) => (
                    <Fragment key={k}>
                      <dt className="text-slate-500">{k}</dt>
                      <dd className="text-slate-700">{val}</dd>
                    </Fragment>
                  ))}
                  {must.length > 0 && (
                    <>
                      <dt className="text-slate-500">Must show</dt>
                      <dd className="text-slate-700">{must.join("; ")}</dd>
                    </>
                  )}
                </dl>
              )}
              {judged && <VerdictDetail item={item} v={v} files={files} />}
              {judged && onOverride && (
                <button onClick={() => onOverride(item)} className="text-xs font-medium text-slate-500 hover:text-brand-700">
                  Override verdict…
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

function VerdictDetail({ item, v, files }: { item: Item; v: Verdict; files?: EvidenceFile[] }) {
  const cites = v.citations ?? [];
  return (
    <div className="space-y-2.5">
      {v.rationale && <p className="text-[13px] leading-relaxed text-slate-700">{v.rationale}</p>}
      {v.source === "requester_override" && v.override_reason && <p className="text-xs text-slate-600">Override reason: {v.override_reason}</p>}
      {v.review_flags?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {v.review_flags.map((f) => (
            <Badge key={f} tone="amber" title="Code-side check on the agent's verdict">
              Review: {f.replace(/_/g, " ")}
            </Badge>
          ))}
        </div>
      )}
      {item.subpoints.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
          {item.subpoints.map((sp) => {
            const sv = v.subpoints?.find((x) => x.key === sp.key);
            return (
              <li key={sp.key} className="px-3 py-2 text-xs">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-slate-800">
                    {sp.text}
                    {sp.condition && <span className="text-slate-500"> ({sp.condition})</span>}
                  </span>
                  <VerdictBadge verdict={sv?.verdict ?? "pending"} />
                </div>
                {sv?.note && <p className="mt-0.5 text-slate-600">{sv.note}</p>}
                {sv?.citations?.length ? <Evidence cites={sv.citations} files={files} /> : null}
              </li>
            );
          })}
        </ul>
      )}
      {cites.length > 0 && <Evidence cites={cites} files={files} open={v.verdict !== "met"} />}
    </div>
  );
}

/** Citations grouped by file, so one file cited on five pages reads as one source. */
function Evidence({ cites, files, open }: { cites: Citation[]; files?: EvidenceFile[]; open?: boolean }) {
  const groups = new Map<string, Citation[]>();
  for (const c of cites) {
    const k = String(c.file_id ?? c.evidence_id);
    const seen = groups.get(k) ?? [];
    if (!seen.some((x) => x.location === c.location && x.quote === c.quote)) seen.push(c);
    groups.set(k, seen);
  }
  return (
    <div className="mt-1.5 space-y-1.5">
      {[...groups.values()].map((g) => (
        <SourceRow key={String(g[0]!.file_id ?? g[0]!.evidence_id)} cites={g} files={files} defaultOpen={open} />
      ))}
    </div>
  );
}

function SourceRow({ cites, files, defaultOpen }: { cites: Citation[]; files?: EvidenceFile[]; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const c0 = cites[0]!;
  const locs = [...new Set(cites.map((c) => c.location).filter(Boolean))];
  const problem = cites.find((c) => c.problem)?.problem;
  const verified = cites.some((c) => c.verified);
  const visual = cites.some((c) => c.visual && !c.problem);
  return (
    <div className={cx("rounded-md border text-xs", problem && !verified ? "border-red-200 bg-red-50/40" : "border-slate-200 bg-slate-50/60")}>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full flex-wrap items-center gap-x-2 gap-y-1 px-2.5 py-1.5 text-left">
        <Icon name="chevronRight" size={13} className={cx("text-slate-500 transition-transform", open && "rotate-90")} />
        <Icon name={c0.file_id && files?.find((f) => f.id === c0.file_id)?.kind === "text" ? "mail" : "file"} size={14} className="text-slate-500" />
        <span className="min-w-0 truncate font-medium text-slate-800">{c0.filename ?? c0.evidence_id}</span>
        {locs.length > 0 && <span className="text-slate-500">{locs.join(", ")}</span>}
        <span className="ml-auto">
          {verified ? (
            <Badge tone="green" title="The quoted text was found at the cited location">
              <Icon name="check" size={11} /> Quote verified
            </Badge>
          ) : visual ? (
            <Badge tone="blue" title="Based on the page image, not on quoted text">
              Visual evidence
            </Badge>
          ) : (
            <Badge tone="red">{problem ?? "Unverified"}</Badge>
          )}
        </span>
      </button>
      {open && (
        <div className="space-y-1.5 border-t border-slate-200 px-2.5 py-2">
          {cites.map((c, i) => (
            <CitationView key={i} c={c} files={files} />
          ))}
        </div>
      )}
    </div>
  );
}

export function CitationView({ c, files }: { c: Citation; files?: EvidenceFile[] }) {
  const f = files?.find((x) => x.id === c.file_id);
  const img = f?.images.find((im) => im.label === c.location);
  const [zoom, setZoom] = useState(false);
  return (
    <div className="text-xs">
      <div className="flex flex-wrap items-center gap-1.5 text-slate-500">
        <span className="font-medium text-slate-700">{c.location || "Message"}</span>
        {c.problem && <span className="text-red-700">· {c.problem}</span>}
        {c.file_id && (
          <a className="ml-auto font-medium text-brand-700 hover:underline" href={`/api/files/${c.file_id}/download`}>
            Download
          </a>
        )}
      </div>
      {c.quote && <blockquote className="mt-1 whitespace-pre-line border-l-2 border-brand-200 bg-white px-2 py-1 font-mono text-[11.5px] leading-relaxed text-slate-800">{c.quote}</blockquote>}
      {c.note && <p className="mt-1 text-slate-600">{c.note}</p>}
      {img && (
        <button onClick={() => setZoom(!zoom)} className="mt-1.5 block" aria-label={zoom ? "Shrink page image" : "Enlarge page image"}>
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
              <div className="flex items-center gap-2">
                <select aria-label={`Item ${i + 1} type`} className={cx(inputCls, "w-36")} value={it.kind} onChange={(e) => set(i, { kind: e.target.value as DraftItem["kind"] })}>
                  <option value="document">Document</option>
                  <option value="answer">Answer</option>
                </select>
                <Button variant="ghost" size="sm" className="ml-auto" onClick={() => onChange(items.filter((_, n) => n !== i))} aria-label={`Remove item ${i + 1}`}>
                  <Icon name="x" size={14} /> Remove
                </Button>
              </div>
              <textarea
                aria-label={`Item ${i + 1}`}
                className={cx(inputCls, "min-h-[56px]")}
                rows={2}
                value={it.description}
                onChange={(e) => set(i, { description: e.target.value })}
                placeholder={it.kind === "answer" ? "The question the provider should answer" : "The document the provider should send, e.g. Signed W-9 form"}
              />
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
