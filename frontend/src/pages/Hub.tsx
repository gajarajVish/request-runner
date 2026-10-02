import { type ReactNode, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate, fmtTime, type HubView } from "../api";
import { Badge, Button, ErrorText, Icon, RefId, Spinner, cx, inputCls } from "../components/ui";

type HubItemT = HubView["items"][number];

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
      <Frame>
        <div className="grid place-items-center py-24 text-slate-500">
          <Spinner />
        </div>
      </Frame>
    );
  if (q.error || !q.data)
    return (
      <Frame>
        <div className="mx-auto max-w-md px-4 py-20 text-center">
          <span className="mx-auto grid h-10 w-10 place-items-center rounded-full bg-slate-200 text-slate-600">
            <Icon name="shield" size={18} />
          </span>
          <h1 className="mt-4 text-[17px] font-semibold text-slate-900">This link is no longer active</h1>
          <p className="mt-2 text-[13px] leading-relaxed text-slate-600">
            It may have expired, or every item on it is already complete. To send something else, reply to the email you received.
          </p>
        </div>
      </Frame>
    );

  const d = q.data;
  const requesters = [...new Set(d.items.map((i) => i.requester))].join(", ");
  const all = d.items.flatMap((i) => i.checklist);
  const received = all.filter((c) => c.status === "received").length;
  const overdue = d.items.filter((i) => i.overdue_days > 0).length;
  const pct = all.length ? Math.round((received / all.length) * 100) : 0;
  const first = d.provider.name?.split(" ")[0];

  return (
    <Frame appName={d.app_name} requester={requesters}>
      <section className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-3xl px-4 py-6 sm:py-8">
          <p className="text-2xs font-semibold uppercase tracking-[0.08em] text-slate-500">Document request</p>
          <h1 className="mt-1 text-[20px] font-semibold tracking-tight text-slate-900 sm:text-[22px]">
            {first ? `Hi ${first}, ` : ""}
            {requesters} needs {d.items.length === 1 ? "1 request" : `${d.items.length} requests`} from you
          </h1>
          <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-slate-600">
            Upload a file or type an answer against each item. Only {requesters} can see what you send here.
          </p>

          <div className="mt-5 grid gap-3 rounded-md border border-slate-200 bg-slate-50/60 p-4 sm:grid-cols-[1fr_auto] sm:items-center">
            <div>
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-[13px] font-medium text-slate-900">
                  <span className="tabular-nums">{received}</span> of <span className="tabular-nums">{all.length}</span> items received
                </p>
                <span className="text-xs tabular-nums text-slate-500">{pct}%</span>
              </div>
              <div
                className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={all.length}
                aria-valuenow={received}
                aria-label={`${received} of ${all.length} items received`}
              >
                <div className={cx("h-full rounded-full", pct === 100 ? "bg-emerald-600" : "bg-brand-600")} style={{ width: `${pct}%` }} />
              </div>
            </div>
            {overdue > 0 ? (
              <Badge tone="red" dot className="justify-self-start sm:justify-self-end">
                {overdue === 1 ? "1 request overdue" : `${overdue} requests overdue`}
              </Badge>
            ) : (
              <Badge tone="slate" dot className="justify-self-start sm:justify-self-end">
                Nothing overdue
              </Badge>
            )}
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-3xl space-y-4 px-4 py-6">
        {d.items.map((it) => (
          <HubItem key={it.request_id} token={token} it={it} onSubmitted={kick} />
        ))}
        <CloseAll token={token} requester={requesters} onDone={kick} />
      </main>
    </Frame>
  );
}

function Frame({ children, appName = "RequestRunner", requester }: { children: ReactNode; appName?: string; requester?: string }) {
  return (
    <div className="min-h-full bg-canvas">
      <header className="bg-ink-900">
        <div className="mx-auto flex h-12 max-w-3xl items-center gap-3 px-4">
          <span className="flex items-center gap-2.5 text-[14px] font-semibold tracking-tight text-white">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-brand-600 ring-1 ring-white/15">
              <Icon name="shield" size={15} className="text-white" />
            </span>
            {appName}
          </span>
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2.5 py-1 text-2xs font-medium text-emerald-300">
            <LockIcon />
            Secure upload
          </span>
        </div>
      </header>
      {children}
      <footer className="mx-auto max-w-3xl px-4 pb-10 pt-2 text-center text-xs leading-relaxed text-slate-500">
        Files are sent over an encrypted connection{requester ? ` and shared only with ${requester}` : ""}. Questions? Reply to the email that brought you here.
      </footer>
    </div>
  );
}

function LockIcon() {
  return (
    <svg viewBox="0 0 20 20" width={12} height={12} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5.5 9h9v7.5h-9zM7.5 9V6.5a2.5 2.5 0 0 1 5 0V9" />
    </svg>
  );
}

function splitLabel(it: HubItemT) {
  const ref = it.label.endsWith(it.title) ? it.label.slice(0, -it.title.length).trim() : "";
  return { ref, title: ref ? it.title : it.label };
}

function HubItem({ token, it, onSubmitted }: { token: string; it: HubItemT; onSubmitted: () => void }) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [answer, setAnswer] = useState("");
  const [msg, setMsg] = useState<{ tone: "ok" | "warn"; text: string } | null>(null);
  const [drag, setDrag] = useState(false);
  const done = it.checklist.length > 0 && it.checklist.every((c) => c.status === "received");
  const got = it.checklist.filter((c) => c.status === "received").length;
  const { ref, title } = splitLabel(it);
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
      setMsg(
        bad.length
          ? { tone: "warn", text: `Couldn't accept ${bad.map((b) => `${b.filename} (${b.reason})`).join("; ")}. Try a PDF, Excel, CSV, Word, image or .eml file.` }
          : { tone: "ok", text: `Received ${res.map((r) => r.filename).join(", ")}. We're checking it against the list now.` },
      );
      refresh();
    },
  });
  const sendAnswer = useMutation({
    mutationFn: () => api.post(`/api/hub/${token}/answer`, { request_id: it.request_id, text: answer }),
    onSuccess: () => {
      setAnswer("");
      setMsg({ tone: "ok", text: "Answer received. We're checking it against the list now." });
      refresh();
    },
  });
  const close = useMutation({
    mutationFn: () => api.post(`/api/hub/${token}/close`, { request_id: it.request_id }),
    onSuccess: () => {
      setMsg({ tone: "ok", text: `Thanks. We've told ${it.requester} you have nothing more to send for this request.` });
      refresh();
    },
  });
  const hasAnswers = it.checklist.some((c) => c.kind === "answer");
  const [showAll, setShowAll] = useState(false);
  const SENT_PREVIEW = 3;
  const sent = showAll ? it.submitted : it.submitted.slice(0, SENT_PREVIEW);

  return (
    <section className={cx("overflow-hidden rounded-md border bg-white shadow-xs", done ? "border-emerald-300" : "border-slate-200")}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-slate-200 px-4 py-3">
        <h2 className="flex min-w-0 basis-full items-baseline gap-2 text-[14px] font-semibold text-slate-900 sm:basis-auto sm:flex-1">
          {ref && <RefId className="whitespace-nowrap">{ref}</RefId>}
          <span className="min-w-0">{title}</span>
        </h2>
        <div className="flex flex-wrap items-center gap-1.5">
          {it.shared && <Badge tone="violet">Shared with a colleague</Badge>}
          {done ? (
            <Badge tone="green" dot>
              All received
            </Badge>
          ) : it.overdue_days > 0 ? (
            <Badge tone="red" dot>
              {it.overdue_days === 1 ? "1 day overdue" : `${it.overdue_days} days overdue`}
            </Badge>
          ) : (
            it.due_date && (
              <Badge tone="slate">
                <Icon name="calendar" size={12} /> Due {fmtDate(it.due_date)}
              </Badge>
            )
          )}
          {it.checklist.length > 0 && !done && (
            <span className="text-xs tabular-nums text-slate-500">
              {got}/{it.checklist.length}
            </span>
          )}
        </div>
      </header>

      <ol className="divide-y divide-slate-100">
        {it.checklist.map((c, idx) => {
          const ok = c.status === "received";
          return (
            <li key={c.key} className="flex items-start gap-3 px-4 py-3">
              <span
                className={cx(
                  "mt-px grid h-5 w-5 shrink-0 place-items-center rounded-full text-2xs font-semibold tabular-nums",
                  ok ? "bg-emerald-600 text-white" : "border border-slate-300 bg-white text-slate-500",
                )}
                aria-hidden
              >
                {ok ? <Icon name="check" size={12} /> : idx + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className={cx("text-[13px] leading-relaxed", ok ? "text-slate-500" : "text-slate-900")}>
                  {c.description}
                  <span className="sr-only">{ok ? " (received)" : " (outstanding)"}</span>
                </p>
                {c.subpoints.length > 0 && !ok && (
                  <ul className="mt-1.5 space-y-0.5 text-xs text-slate-600">
                    {c.subpoints.map((s, i) => (
                      <li key={i} className="flex gap-2">
                        <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-slate-400" aria-hidden />
                        {s}
                      </li>
                    ))}
                  </ul>
                )}
                {c.missing.length > 0 && (
                  <div className="mt-2 rounded border-l-2 border-amber-500 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
                    <p className="font-semibold">Still needed</p>
                    <ul className="mt-0.5 space-y-0.5">
                      {c.missing.map((m, i) => (
                        <li key={i}>{m}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
              {ok && <span className="hidden text-2xs font-medium uppercase tracking-[0.06em] text-emerald-700 sm:block">Received</span>}
            </li>
          );
        })}
      </ol>

      <div className="space-y-3 border-t border-slate-200 bg-slate-50/50 px-4 py-4">
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
              className={cx(
                "flex items-center gap-3 rounded-md border border-dashed px-4 py-3 transition-colors",
                drag ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-white",
              )}
            >
              <input ref={fileRef} type="file" multiple hidden accept=".pdf,.xlsx,.xls,.csv,.png,.jpg,.jpeg,.heic,.docx,.eml" onChange={(e) => e.target.files && upload.mutate([...e.target.files])} />
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-slate-100 text-slate-600">
                {upload.isPending ? <Spinner /> : <Icon name="upload" />}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] text-slate-800">
                  {upload.isPending ? (
                    "Uploading…"
                  ) : (
                    <>
                      <span className="hidden sm:inline">Drag files here, or browse</span>
                      <span className="sm:hidden">Upload files</span>
                    </>
                  )}
                </p>
                <p className="text-xs text-slate-500">
                  <span className="hidden sm:inline">PDF, Excel, CSV, Word, images or .eml · up to 25 MB each</span>
                  <span className="sm:hidden">PDF, Excel, Word, images · 25 MB max</span>
                </p>
              </div>
              <Button size="sm" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
                Browse
              </Button>
            </div>

            <div className="space-y-2">
              <label className="sr-only" htmlFor={`answer-${it.request_id}`}>
                {hasAnswers ? "Your answer" : "Note"}
              </label>
              <textarea
                id={`answer-${it.request_id}`}
                className={cx(inputCls, "min-h-[64px]")}
                placeholder={hasAnswers ? "Type your answer" : "Add a note (optional)"}
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
              />
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <Button size="sm" variant="primary" disabled={!answer.trim()} busy={sendAnswer.isPending} onClick={() => sendAnswer.mutate()}>
                  <Icon name="send" size={13} />
                  {hasAnswers ? "Send answer" : "Send note"}
                </Button>
                <button
                  className="ml-auto text-xs font-medium text-slate-600 underline-offset-2 hover:text-slate-900 hover:underline"
                  onClick={() => confirm(`Tell ${it.requester} you have nothing more to send for ${it.label}?`) && close.mutate()}
                >
                  I have nothing more for this request
                </button>
              </div>
            </div>
          </>
        )}

        {msg && (
          <p
            role="status"
            className={cx(
              "flex items-start gap-2 rounded-md border px-3 py-2 text-xs",
              msg.tone === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900",
            )}
          >
            <Icon name={msg.tone === "ok" ? "check" : "alert"} size={14} className="mt-px" />
            {msg.text}
          </p>
        )}
        <ErrorText error={upload.error || sendAnswer.error || close.error} />

        {it.submitted.length > 0 && (
          <div>
            <p className="mb-1.5 text-2xs font-semibold uppercase tracking-[0.08em] text-slate-500">You've sent</p>
            <ul className="divide-y divide-slate-100 rounded-md border border-slate-200 bg-white">
              {sent.map((f, i) => (
                <li key={i} className="flex items-center gap-2.5 px-3 py-2 text-xs">
                  <Icon name={f.kind === "text" ? "mail" : "file"} size={14} className="text-slate-400" />
                  <span className="min-w-0 flex-1 truncate text-slate-800">{f.kind === "text" ? "Typed answer" : f.filename}</span>
                  {f.status === "unreadable" && (
                    <Badge tone="red" title="We couldn't read this file. Please send it again in another format.">
                      Unreadable
                    </Badge>
                  )}
                  <span className="shrink-0 tabular-nums text-slate-500">{fmtTime(f.at)}</span>
                </li>
              ))}
            </ul>
            {it.submitted.length > SENT_PREVIEW && (
              <button onClick={() => setShowAll(!showAll)} aria-expanded={showAll} className="mt-1.5 text-xs font-medium text-brand-700 hover:underline">
                {showAll ? "Show less" : `Show all ${it.submitted.length}`}
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function CloseAll({ token, requester, onDone }: { token: string; requester: string; onDone: () => void }) {
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => api.post(`/api/hub/${token}/close`, {}),
    onSuccess: () => {
      onDone();
      qc.invalidateQueries({ queryKey: ["hub", token] });
    },
  });
  return (
    <div className="flex flex-col items-start gap-3 rounded-md border border-slate-200 bg-white px-4 py-4 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-slate-900">Finished?</p>
        <p className="text-xs text-slate-600">Let {requester} know you've sent everything you can. Anything still open goes back to them.</p>
      </div>
      <Button
        size="sm"
        busy={m.isPending}
        onClick={() => confirm(`Tell ${requester} you've sent everything you have for all of these requests?`) && m.mutate()}
      >
        I've sent everything I have
      </Button>
      <ErrorText error={m.error} />
    </div>
  );
}
