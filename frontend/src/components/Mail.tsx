import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtTime, type Inbound, type Outbound } from "../api";
import { Badge, Button, Disclosure, ErrorText, cx, inputCls, type Tone } from "./ui";

const STATUS_TONE: Record<string, Tone> = { sent: "green", queued: "blue", sending: "blue", draft: "slate", failed: "red", uncertain: "amber", cancelled: "slate" };

export function OutboundView({ m, compact }: { m: Outbound; compact?: boolean }) {
  const qc = useQueryClient();
  const resend = useMutation({ mutationFn: () => api.post(`/api/messages/${m.id}/resend`), onSuccess: () => qc.invalidateQueries() });
  return (
    <div className="rounded-md border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-2 text-xs">
        <Badge tone={STATUS_TONE[m.status] ?? "slate"}>{m.status}</Badge>
        <Badge tone="slate">{m.kind.replace(/_/g, " ")}</Badge>
        {m.counted_request_ids.length > 0 && <Badge tone="violet" title="Counts toward the automatic follow-up limit">counted</Badge>}
        <span className="font-medium text-slate-700">{m.subject}</span>
        <span className="ml-auto text-slate-400">{fmtTime(m.sent_at ?? m.created_at)}</span>
      </div>
      <div className="space-y-0.5 px-3 py-2 text-xs text-slate-600">
        <div>
          <span className="text-slate-400">To:</span> {m.to.join(", ")}
          {m.cc.length > 0 && (
            <>
              {" "}
              <span className="text-slate-400">Cc:</span> {m.cc.join(", ")}
            </>
          )}
        </div>
        {!compact && (
          <Disclosure summary="Headers">
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px] text-slate-500">
              <dt>From</dt>
              <dd className="break-all">{m.from}</dd>
              <dt>Reply-To</dt>
              <dd className="break-all">{m.reply_to}</dd>
              <dt>Message-ID</dt>
              <dd className="break-all">{m.message_id}</dd>
              {m.in_reply_to && (
                <>
                  <dt>In-Reply-To</dt>
                  <dd className="break-all">{m.in_reply_to}</dd>
                </>
              )}
              <dt>Attempts</dt>
              <dd>{m.attempts}</dd>
            </dl>
          </Disclosure>
        )}
      </div>
      <pre className="mail border-t border-slate-100 px-3 py-2 text-slate-700">{m.text}</pre>
      {(m.status === "uncertain" || m.status === "failed") && (
        <div className="flex items-center gap-2 border-t border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <span className="flex-1">{m.status === "uncertain" ? "We can't tell whether this was delivered, so it won't be resent automatically." : `Delivery failed: ${m.last_error}`}</span>
          <Button size="sm" onClick={() => resend.mutate()} busy={resend.isPending}>
            Resend
          </Button>
        </div>
      )}
      <ErrorText error={resend.error} />
    </div>
  );
}

export function InboundView({ m }: { m: Inbound }) {
  const tone: Tone = m.status === "processed" ? "green" : m.status === "unmatched" ? "amber" : m.status === "error" ? "red" : "slate";
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-2 text-xs">
        <Badge tone="blue">received</Badge>
        <Badge tone={tone}>{m.status.replace(/_/g, " ")}</Badge>
        {m.match_method && <Badge tone="slate">matched by {m.match_method.replace(/_/g, " ")}</Badge>}
        {m.is_auto_reply && <Badge tone="amber">auto-reply</Badge>}
        {m.sender_is_owner === false && <Badge tone="amber">unknown sender</Badge>}
        <span className="font-medium text-slate-700">{m.subject}</span>
        <span className="ml-auto text-slate-400">{fmtTime(m.received_at)}</span>
      </div>
      <div className="px-3 py-2 text-xs text-slate-600">
        <span className="text-slate-400">From:</span> {m.from_name ? `${m.from_name} <${m.from}>` : m.from}
        <Disclosure summary="Headers">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px] text-slate-500">
            <dt>To</dt>
            <dd className="break-all">{m.to.join(", ")}</dd>
            <dt>Message-ID</dt>
            <dd className="break-all">{m.message_id}</dd>
            {m.in_reply_to && (
              <>
                <dt>In-Reply-To</dt>
                <dd className="break-all">{m.in_reply_to}</dd>
              </>
            )}
            {m.match_notes?.length > 0 && (
              <>
                <dt>Matching</dt>
                <dd>{m.match_notes.join("; ")}</dd>
              </>
            )}
          </dl>
        </Disclosure>
      </div>
      {/* provider text is untrusted: rendered as plain text only */}
      <pre className="mail border-t border-slate-100 px-3 py-2 text-slate-700">{m.text || "(no new text)"}</pre>
      {m.error && <p className="border-t border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700">{m.error}</p>}
    </div>
  );
}

export function DraftEditor({ m, onSend, sendLabel = "Send", busy, extra }: { m: Outbound; onSend?: (text: string) => void; sendLabel?: string; busy?: boolean; extra?: React.ReactNode }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(m.text);
  const save = useMutation({ mutationFn: () => api.put(`/api/messages/${m.id}/draft`, { text }), onSuccess: () => { setEditing(false); qc.invalidateQueries(); } });
  return (
    <div className="rounded-md border border-brand-100 bg-white">
      <div className="space-y-0.5 border-b border-slate-100 px-3 py-2 text-xs text-slate-600">
        <div>
          <span className="text-slate-400">From:</span> {m.from}
        </div>
        <div>
          <span className="text-slate-400">To:</span> {m.to.join(", ")}
          {m.cc.length > 0 && ` · Cc: ${m.cc.join(", ")}`}
        </div>
        <div>
          <span className="text-slate-400">Reply-To:</span> <span className="font-mono">{m.reply_to}</span>
        </div>
        <div className="font-medium text-slate-800">{m.subject}</div>
      </div>
      {editing ? (
        <textarea className={cx(inputCls, "mail min-h-[280px] rounded-none border-0 font-mono text-xs shadow-none focus:ring-0")} value={text} onChange={(e) => setText(e.target.value)} />
      ) : (
        <pre className="mail max-h-[420px] overflow-y-auto px-3 py-2 text-slate-700">{m.text}</pre>
      )}
      {m.status === "draft" && (
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-3 py-2">
          {editing ? (
            <>
              <Button size="sm" onClick={() => save.mutate()} busy={save.isPending}>
                Save edits
              </Button>
              <Button size="sm" variant="ghost" onClick={() => { setText(m.text); setEditing(false); }}>
                Cancel
              </Button>
            </>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
              Edit text
            </Button>
          )}
          {extra}
          {onSend && (
            <Button size="sm" variant="primary" className="ml-auto" disabled={editing} busy={busy} onClick={() => onSend(m.text)}>
              {sendLabel}
            </Button>
          )}
        </div>
      )}
      <ErrorText error={save.error} />
    </div>
  );
}
