import { useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate, fmtTime, type HubView } from "../api";
import { Badge, Button, ErrorText, Spinner, cx, inputCls } from "../components/ui";

/** The provider's page: no account, opened from the link in their email. */
export function HubPage() {
  const token = useParams().token!;
  const [busyUntil, setBusyUntil] = useState(0);
  const q = useQuery({
    queryKey: ["hub", token],
    queryFn: () => api.get<HubView>(`/api/hub/${token}`),
    retry: false,
    // after a submission, poll briefly so the checklist updates once it's been checked
    refetchInterval: () => (Date.now() < busyUntil ? 3000 : false),
  });
  const kick = () => setBusyUntil(Date.now() + 60_000);

  if (q.isLoading)
    return (
      <div className="grid h-full place-items-center text-slate-400">
        <Spinner />
      </div>
    );
  if (q.error || !q.data)
    return (
      <div className="mx-auto max-w-md px-4 py-20 text-center">
        <h1 className="text-lg font-semibold">This link isn't active</h1>
        <p className="mt-2 text-sm text-slate-600">It may have expired, or everything on it is already done. Reply to the email you received if you still need to send something.</p>
      </div>
    );
  const d = q.data;
  const requesters = [...new Set(d.items.map((i) => i.requester))].join(", ");
  return (
    <div className="min-h-full bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-3xl px-4 py-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{d.app_name}</p>
          <h1 className="mt-1 text-xl font-semibold">Hi {d.provider.name?.split(" ")[0] || d.provider.email},</h1>
          <p className="mt-1 text-sm text-slate-600">
            {requesters} asked for the {d.items.length === 1 ? "item" : `${d.items.length} items`} below. Upload a file or type an answer against each one. Everything you send here goes only to {requesters}.
          </p>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-4 px-4 py-6">
        {d.items.map((it) => (
          <HubItem key={it.request_id} token={token} it={it} onSubmitted={kick} />
        ))}
        <CloseAll token={token} onDone={kick} />
      </main>
    </div>
  );
}

function HubItem({ token, it, onSubmitted }: { token: string; it: HubView["items"][number]; onSubmitted: () => void }) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [answer, setAnswer] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const done = it.checklist.length > 0 && it.checklist.every((c) => c.status === "received");
  const refresh = () => {
    onSubmitted();
    qc.invalidateQueries({ queryKey: ["hub", token] });
  };
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const out = [];
      for (const f of files) {
        const fd = new FormData();
        fd.append("file", f);
        fd.append("request_id", String(it.request_id));
        out.push(await api.form<{ accepted: boolean; reason: string | null; filename: string }>(`/api/hub/${token}/upload`, fd));
      }
      return out;
    },
    onSuccess: (res) => {
      const bad = res.filter((r) => !r.accepted);
      setMsg(bad.length ? `Not accepted: ${bad.map((b) => `${b.filename} (${b.reason})`).join("; ")}` : `Received ${res.map((r) => r.filename).join(", ")}. We're checking it now.`);
      refresh();
    },
  });
  const sendAnswer = useMutation({
    mutationFn: () => api.post(`/api/hub/${token}/answer`, { request_id: it.request_id, text: answer }),
    onSuccess: () => {
      setAnswer("");
      setMsg("Answer received. We're checking it now.");
      refresh();
    },
  });
  const close = useMutation({
    mutationFn: () => api.post(`/api/hub/${token}/close`, { request_id: it.request_id }),
    onSuccess: () => {
      setMsg("Thanks. We've told the requester that's everything you have for this item.");
      refresh();
    },
  });
  const hasAnswers = it.checklist.some((c) => c.kind === "answer");

  return (
    <section className={cx("rounded-lg border bg-white shadow-sm", done ? "border-emerald-200" : "border-slate-200")}>
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
        <h2 className="flex-1 font-semibold text-slate-800">{it.label}</h2>
        {it.shared && <Badge tone="violet">shared with a colleague</Badge>}
        {it.overdue_days > 0 ? <Badge tone="red">{it.overdue_days} days overdue</Badge> : it.due_date && <Badge>due {fmtDate(it.due_date)}</Badge>}
        {done && <Badge tone="green">✓ all received</Badge>}
      </header>
      <div className="space-y-4 p-4">
        <ul className="space-y-2">
          {it.checklist.map((c) => (
            <li key={c.key} className="flex items-start gap-2 text-sm">
              <span className={cx("mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px]", c.status === "received" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-400")}>{c.status === "received" ? "✓" : "•"}</span>
              <div>
                <p className={c.status === "received" ? "text-slate-500" : "text-slate-800"}>{c.description}</p>
                {c.subpoints.length > 0 && (
                  <ul className="mt-0.5 list-disc pl-5 text-xs text-slate-500">
                    {c.subpoints.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                )}
                {c.missing.length > 0 && (
                  <ul className="mt-1 text-xs text-amber-800">
                    {c.missing.map((m, i) => (
                      <li key={i}>Still needed: {m}</li>
                    ))}
                  </ul>
                )}
              </div>
            </li>
          ))}
        </ul>

        {!done && (
          <>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag(false);
                const files = [...e.dataTransfer.files];
                if (files.length) upload.mutate(files);
              }}
              className={cx("rounded-md border-2 border-dashed px-4 py-5 text-center text-sm", drag ? "border-brand-500 bg-brand-50" : "border-slate-300")}
            >
              <input ref={fileRef} type="file" multiple hidden accept=".pdf,.xlsx,.xls,.csv,.png,.jpg,.jpeg,.heic,.docx,.eml" onChange={(e) => e.target.files && upload.mutate([...e.target.files])} />
              {upload.isPending ? (
                <span className="inline-flex items-center gap-2 text-slate-600">
                  <Spinner /> Uploading…
                </span>
              ) : (
                <>
                  <span className="text-slate-600">Drop files here or </span>
                  <button className="font-medium text-brand-700 hover:underline" onClick={() => fileRef.current?.click()}>
                    choose files
                  </button>
                  <p className="mt-1 text-xs text-slate-400">PDF, Excel, CSV, Word, images or .eml · up to 25 MB each</p>
                </>
              )}
            </div>
            <div className="space-y-2">
              <textarea className={cx(inputCls, "min-h-[70px]")} placeholder={hasAnswers ? "Type your answer here" : "Anything to add? (optional)"} value={answer} onChange={(e) => setAnswer(e.target.value)} />
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="primary" disabled={!answer.trim()} busy={sendAnswer.isPending} onClick={() => sendAnswer.mutate()}>
                  Send answer
                </Button>
                <button className="ml-auto text-xs text-slate-500 hover:text-slate-700 hover:underline" onClick={() => confirm("Tell the requester you have nothing more to send for this item?") && close.mutate()}>
                  I don't have anything more for this
                </button>
              </div>
            </div>
          </>
        )}
        {msg && <p className="rounded bg-slate-50 px-3 py-2 text-xs text-slate-700">{msg}</p>}
        <ErrorText error={upload.error || sendAnswer.error || close.error} />
        {it.submitted.length > 0 && (
          <div className="border-t border-slate-100 pt-3">
            <p className="mb-1 text-xs font-medium text-slate-500">You've sent</p>
            <ul className="space-y-0.5 text-xs text-slate-600">
              {it.submitted.map((f, i) => (
                <li key={i}>
                  {f.kind === "text" ? "Typed answer" : f.filename} · {fmtTime(f.at)}
                  {f.status === "unreadable" && <span className="text-red-600"> · we couldn't read this file</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

function CloseAll({ token, onDone }: { token: string; onDone: () => void }) {
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => api.post(`/api/hub/${token}/close`, {}),
    onSuccess: () => {
      onDone();
      qc.invalidateQueries({ queryKey: ["hub", token] });
    },
  });
  return (
    <div className="pt-2 text-center">
      <button className="text-xs text-slate-500 hover:text-slate-700 hover:underline" onClick={() => confirm("Tell the requester you've sent everything you have for all of these items?") && m.mutate()}>
        That's everything I have for all items
      </button>
      <ErrorText error={m.error} />
    </div>
  );
}
