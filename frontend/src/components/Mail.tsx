import { useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, fmtTime, type Inbound, type Outbound } from "../api";
import { Badge, Button, Disclosure, ErrorText, Icon, cx, inputCls, type Tone } from "./ui";

const STATUS_TONE: Record<string, Tone> = { sent: "green", queued: "blue", sending: "blue", draft: "slate", failed: "red", uncertain: "amber", cancelled: "slate" };
const STATUS_LABEL: Record<string, string> = { sent: "Sent", queued: "Queued", sending: "Sending", draft: "Draft", failed: "Failed", uncertain: "Delivery unknown", cancelled: "Cancelled" };

export function mailStatusTone(status: string): Tone {
  return STATUS_TONE[status] ?? "slate";
}
export function mailStatusLabel(status: string) {
  return STATUS_LABEL[status] ?? status;
}
function kindLabel(kind: string) {
  const s = kind.replace(/_/g, " ");
  return s[0]!.toUpperCase() + s.slice(1);
}

/** Label / value rows, like a mail client's header block. */
function HeaderGrid({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="break-words text-slate-800">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function TechDetails({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <Disclosure summary="Technical details">
      <dl className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 gap-y-0.5 font-mono text-2xs text-slate-600">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-slate-500">{k}</dt>
            <dd className="break-all">{v}</dd>
          </div>
        ))}
      </dl>
    </Disclosure>
  );
}

/** Plain-text body. Provider text is untrusted: always rendered as text, never HTML. */
function Body({ text, className }: { text: string; className?: string }) {
  return <div className={cx("whitespace-pre-wrap break-words px-4 py-3 text-[13px] leading-relaxed text-slate-800", className)}>{text}</div>;
}

export function OutboundView({ m, compact }: { m: Outbound; compact?: boolean }) {
  const qc = useQueryClient();
  const resend = useMutation({ mutationFn: () => api.post(`/api/messages/${m.id}/resend`), onSuccess: () => qc.invalidateQueries() });
  const rows: [string, ReactNode][] = [
    ["From", m.from],
    ["To", m.to.join(", ")],
    ...(m.cc.length ? ([["Cc", m.cc.join(", ")]] as [string, ReactNode][]) : []),
    ...(!compact && m.reply_to ? ([["Reply-To", <span className="font-mono text-2xs">{m.reply_to}</span>]] as [string, ReactNode][]) : []),
  ];
  return (
    <article className="overflow-hidden rounded-md border border-slate-200 bg-white">
      <header className="space-y-2.5 border-b border-slate-200 bg-slate-50/60 px-4 py-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Icon name="send" size={14} className="text-slate-500" />
          <Badge tone={mailStatusTone(m.status)} dot>
            {mailStatusLabel(m.status)}
          </Badge>
          <Badge>{kindLabel(m.kind)}</Badge>
          {m.counted_request_ids.length > 0 && (
            <Badge tone="violet" title="Counts toward the automatic follow-up limit">
              Counts toward limit
            </Badge>
          )}
          <time className="ml-auto text-xs tabular-nums text-slate-500">{fmtTime(m.sent_at ?? m.created_at)}</time>
        </div>
        <p className="text-[14px] font-semibold text-slate-900">{m.subject}</p>
        <HeaderGrid rows={compact ? rows.filter(([k]) => k !== "From") : rows} />
        {!compact && (
          <TechDetails
            rows={[
              ["Message-ID", m.message_id],
              ...(m.in_reply_to ? ([["In-Reply-To", m.in_reply_to]] as [string, ReactNode][]) : []),
              ["Attempts", m.attempts],
            ]}
          />
        )}
      </header>
      <Body text={m.text} className={compact ? "max-h-72 overflow-y-auto" : undefined} />
      {(m.status === "uncertain" || m.status === "failed") && (
        <div className="flex items-center gap-2 border-t border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-900">
          <Icon name="alert" />
          <span className="flex-1">{m.status === "uncertain" ? "We can't tell whether this was delivered, so it won't be resent automatically." : `Delivery failed: ${m.last_error}`}</span>
          <Button size="sm" onClick={() => resend.mutate()} busy={resend.isPending}>
            Resend
          </Button>
        </div>
      )}
      {resend.error ? (
        <div className="px-4 pb-3">
          <ErrorText error={resend.error} />
        </div>
      ) : null}
    </article>
  );
}

export function InboundView({ m }: { m: Inbound }) {
  const tone: Tone = m.status === "processed" ? "green" : m.status === "unmatched" ? "amber" : m.status === "error" ? "red" : "slate";
  const status = m.status.replace(/_/g, " ");
  return (
    <article className="overflow-hidden rounded-md border border-slate-200 border-l-2 border-l-brand-500 bg-white">
      <header className="space-y-2.5 border-b border-slate-200 bg-brand-50/40 px-4 py-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Icon name="inbox" size={14} className="text-brand-700" />
          <Badge tone="blue">Received</Badge>
          <Badge tone={tone} dot>
            {status[0]!.toUpperCase() + status.slice(1)}
          </Badge>
          {m.match_method && <Badge>Matched by {m.match_method.replace(/_/g, " ")}</Badge>}
          {m.is_auto_reply && <Badge tone="amber">Auto-reply</Badge>}
          {m.sender_is_owner === false && <Badge tone="amber">Unknown sender</Badge>}
          <time className="ml-auto text-xs tabular-nums text-slate-500">{fmtTime(m.received_at)}</time>
        </div>
        <p className="text-[14px] font-semibold text-slate-900">{m.subject || "(no subject)"}</p>
        <HeaderGrid rows={[["From", m.from_name ? `${m.from_name} <${m.from}>` : m.from ?? "unknown"]]} />
        <TechDetails
          rows={[
            ["To", m.to.join(", ")],
            ["Message-ID", m.message_id ?? ""],
            ...(m.in_reply_to ? ([["In-Reply-To", m.in_reply_to]] as [string, ReactNode][]) : []),
            ...(m.match_notes?.length ? ([["Matching", m.match_notes.join("; ")]] as [string, ReactNode][]) : []),
          ]}
        />
      </header>
      {/* provider text is untrusted: rendered as plain text only */}
      <Body text={m.text || "(no new text)"} />
      {m.error && (
        <p className="flex items-start gap-1.5 border-t border-red-200 bg-red-50 px-4 py-2 text-xs text-red-800">
          <Icon name="alert" className="mt-px" />
          {m.error}
        </p>
      )}
    </article>
  );
}

export function DraftEditor({ m, onSend, sendLabel = "Send", busy, extra }: { m: Outbound; onSend?: (text: string) => void; sendLabel?: string; busy?: boolean; extra?: React.ReactNode }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(m.text);
  const save = useMutation({
    mutationFn: () => api.put(`/api/messages/${m.id}/draft`, { text }),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries();
    },
  });
  return (
    <article className="overflow-hidden rounded-md border border-slate-300 bg-white shadow-xs">
      <header className="space-y-2.5 border-b border-slate-200 bg-slate-50/60 px-4 py-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Icon name="mail" size={14} className="text-slate-500" />
          <Badge tone={mailStatusTone(m.status)} dot>
            {m.status === "draft" ? "Draft, not sent" : mailStatusLabel(m.status)}
          </Badge>
          {editing && <Badge tone="amber">Editing</Badge>}
        </div>
        <p className="text-[14px] font-semibold text-slate-900">{m.subject}</p>
        <HeaderGrid
          rows={[
            ["From", m.from],
            ["To", m.to.join(", ")],
            ...(m.cc.length ? ([["Cc", m.cc.join(", ")]] as [string, ReactNode][]) : []),
            ["Reply-To", <span className="font-mono text-2xs">{m.reply_to}</span>],
          ]}
        />
      </header>
      {editing ? (
        <textarea
          aria-label="Email text"
          className={cx(inputCls, "min-h-[320px] rounded-none border-0 px-4 py-3 font-mono text-xs leading-relaxed shadow-none focus:ring-0")}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      ) : (
        <Body text={m.text} className="max-h-[480px] overflow-y-auto" />
      )}
      {m.status === "draft" && (
        <footer className="flex flex-wrap items-center gap-2 border-t border-slate-200 bg-slate-50/60 px-4 py-2.5">
          {editing ? (
            <>
              <Button size="sm" onClick={() => save.mutate()} busy={save.isPending}>
                Save edits
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setText(m.text);
                  setEditing(false);
                }}
              >
                Discard edits
              </Button>
            </>
          ) : (
            <Button size="sm" onClick={() => setEditing(true)}>
              Edit text
            </Button>
          )}
          {extra}
          {onSend && (
            <Button size="sm" variant="primary" className="ml-auto" disabled={editing} busy={busy} onClick={() => onSend(m.text)}>
              <Icon name="send" size={14} />
              {sendLabel}
            </Button>
          )}
        </footer>
      )}
      {save.error ? (
        <div className="px-4 pb-3">
          <ErrorText error={save.error} />
        </div>
      ) : null}
    </article>
  );
}
