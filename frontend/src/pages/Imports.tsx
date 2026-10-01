import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, fmtTime, type ImportListSummary } from "../api";
import { Badge, Button, Card, Empty, ErrorText, Field, inputCls } from "../components/ui";

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
    <div className="space-y-6">
      <Card title="Import a request list">
        <form
          className="grid gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            if (file) upload.mutate();
          }}
        >
          <Field label="CSV file" hint="Columns: request_id, title, instructions, due_date, owner_name, owner_email, backup_email">
            <input type="file" accept=".csv,text/csv" className={inputCls} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </Field>
          <Field label="List name" hint="Re-importing into the same list updates it instead of duplicating it.">
            <input className={inputCls} list="list-names" value={name} placeholder={file?.name.replace(/\.csv$/i, "") ?? "Q3 audit PBC"} onChange={(e) => setName(e.target.value)} />
            <datalist id="list-names">
              {lists.data?.map((l) => (
                <option key={l.id} value={l.name} />
              ))}
            </datalist>
          </Field>
          <Button variant="primary" disabled={!file} busy={upload.isPending} className="sm:mb-5">
            Upload and review
          </Button>
        </form>
        <ErrorText error={upload.error} />
      </Card>

      {lists.data?.length === 0 && <Empty>No lists imported yet.</Empty>}
      {lists.data?.map((l) => (
        <Card key={l.id} title={l.name} actions={<Link className="text-xs text-brand-700 hover:underline" to={`/dashboard?list=${l.id}`}>Dashboard →</Link>}>
          <table className="w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {l.batches.map((b) => (
                <tr key={b.id}>
                  <td className="py-2">
                    <Link to={`/imports/${b.id}`} className="font-medium text-brand-700 hover:underline">
                      {b.filename}
                    </Link>
                  </td>
                  <td className="py-2">
                    <Badge tone={b.status === "applied" ? "green" : b.status === "review" ? "blue" : b.status === "error" ? "red" : "slate"}>{b.status}</Badge>
                  </td>
                  <td className="py-2 text-xs text-slate-500">
                    {Object.entries(b.summary)
                      .map(([k, v]) => `${v} ${k}`)
                      .join(" · ")}
                  </td>
                  <td className="py-2 text-right text-xs text-slate-400">{fmtTime(b.applied_at ?? b.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ))}
    </div>
  );
}
