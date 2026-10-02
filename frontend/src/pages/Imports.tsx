import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, fmtTime, type ImportListSummary } from "../api";
import { Badge, Button, Card, Empty, ErrorText, Field, Icon, PageHeader, cx, inputCls, th, td, type Tone } from "../components/ui";

const STATUS: Record<string, { tone: Tone; label: string }> = {
  analyzing: { tone: "violet", label: "Analyzing" },
  review: { tone: "blue", label: "In review" },
  applied: { tone: "green", label: "Applied" },
  error: { tone: "red", label: "Error" },
  discarded: { tone: "slate", label: "Discarded" },
};
const SUMMARY_TONE: Record<string, Tone> = { new: "blue", changed: "amber", blocked: "red", error: "red", removed: "red" };
const SUMMARY_LABEL: Record<string, string> = { duplicate: "merged", blocked: "held back" };

export function ImportsPage() {
  const nav = useNavigate();
  const lists = useQuery({ queryKey: ["imports"], queryFn: () => api.get<ImportListSummary[]>("/api/imports") });
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const upload = useMutation({
    mutationFn: () => {
      const f = new FormData();
      f.append("file", file!);
      f.append("list_name", name);
      return api.form<{ id: number }>("/api/imports", f);
    },
    onSuccess: (b) => nav(`/imports/${b.id}`),
  });
  return (
    <div>
      <PageHeader
        title="Request lists"
        meta={<span>Upload a list as CSV. Each row becomes a request, and each person gets one email covering everything they owe.</span>}
      />
      <div className="space-y-6">
        <Card title="Import a request list">
          <form
            className="grid gap-4 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto] md:items-start"
            onSubmit={(e) => {
              e.preventDefault();
              if (file) upload.mutate();
            }}
          >
            <Field label="CSV file" hint={<span className="font-mono text-2xs">request_id, title, instructions, due_date, owner_name, owner_email, backup_email</span>}>
              <label className={cx("flex h-8 cursor-pointer items-center gap-2 rounded-md border border-dashed px-2.5 text-[13px] shadow-xs", file ? "border-brand-500 bg-brand-50/50 text-slate-900" : "border-slate-300 bg-white text-slate-500 hover:border-slate-400")}>
                <Icon name="upload" size={14} className={file ? "text-brand-700" : "text-slate-400"} />
                <span className="truncate">{file ? file.name : "Choose a .csv file"}</span>
                <input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </label>
            </Field>
            <Field label="List name" hint="Re-importing into the same list updates it instead of duplicating it.">
              <input className={inputCls} list="list-names" value={name} placeholder={file?.name.replace(/\.csv$/i, "") ?? "Q3 audit PBC"} onChange={(e) => setName(e.target.value)} />
              <datalist id="list-names">
                {lists.data?.map((l) => (
                  <option key={l.id} value={l.name} />
                ))}
              </datalist>
            </Field>
            <Button variant="primary" disabled={!file} busy={upload.isPending} className="md:mt-5">
              Upload and review
            </Button>
          </form>
          <ErrorText error={upload.error} />
        </Card>

        {lists.data?.length === 0 && <Empty icon="imports">No lists imported yet. Upload a CSV above to get started.</Empty>}
        {lists.data?.map((l) => (
          <Card
            key={l.id}
            flush
            title={
              <span className="flex items-center gap-2">
                {l.name}
                <Badge>
                  {l.batches.length} import{l.batches.length === 1 ? "" : "s"}
                </Badge>
              </span>
            }
            actions={
              <Link className="inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline" to={`/dashboard?list=${l.id}`}>
                Dashboard <Icon name="chevronRight" size={12} />
              </Link>
            }
          >
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead className="border-b border-slate-200 bg-slate-50">
                  <tr>
                    <th className={th}>File</th>
                    <th className={th}>Status</th>
                    <th className={cx(th, "hidden sm:table-cell")}>Rows</th>
                    <th className={cx(th, "text-right")}>Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {l.batches.map((b) => {
                    const st = STATUS[b.status] ?? { tone: "slate" as Tone, label: b.status };
                    return (
                      <tr key={b.id} className="hover:bg-slate-50">
                        <td className={td}>
                          <Link to={`/imports/${b.id}`} className="inline-flex items-center gap-2 font-medium text-slate-900 hover:text-brand-700">
                            <Icon name="file" size={14} className="text-slate-400" />
                            {b.filename}
                          </Link>
                        </td>
                        <td className={td}>
                          <Badge tone={st.tone} dot>
                            {st.label}
                          </Badge>
                        </td>
                        <td className={cx(td, "hidden sm:table-cell")}>
                          <span className="flex flex-wrap gap-1">
                            {Object.entries(b.summary).map(([k, v]) => (
                              <Badge key={k} tone={v ? (SUMMARY_TONE[k] ?? "slate") : "slate"}>
                                <span className="tabular-nums">{v}</span> {SUMMARY_LABEL[k] ?? k}
                              </Badge>
                            ))}
                          </span>
                        </td>
                        <td className={cx(td, "whitespace-nowrap text-right text-xs tabular-nums text-slate-500")}>{fmtTime(b.applied_at ?? b.created_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
