import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Inbound, type Me, type RequestSummary } from "../api";
import { InboundView } from "../components/Mail";
import { useMe } from "../components/Shell";
import { Button, Card, Empty, ErrorText, Field, Tabs, inputCls } from "../components/ui";

export function InboxPage() {
  const me = useMe();
  const [tab, setTab] = useState<"unmatched" | "all">("unmatched");
  const q = useQuery({ queryKey: ["inbound", tab], queryFn: () => api.get<Inbound[]>(`/api/inbound${tab === "unmatched" ? "?status=unmatched" : ""}`) });
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Inbox</h1>
        <p className="text-sm text-slate-500">Replies that couldn't be matched to a request safely wait here for you. Mail is never assigned by sender address alone.</p>
      </div>
      {me.data?.dev && <InjectCard me={me.data} />}
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "unmatched", label: "Needs assigning" },
          { id: "all", label: "All received mail" },
        ]}
      />
      {q.data?.length === 0 && <Empty>{tab === "unmatched" ? "Nothing waiting. Every reply was matched." : "No mail received yet."}</Empty>}
      <div className="space-y-4">
        {q.data?.map((m) => (
          <div key={m.id} className="space-y-2">
            <InboundView m={m} />
            {m.status === "unmatched" && <Assign m={m} />}
          </div>
        ))}
      </div>
    </div>
  );
}

function Assign({ m }: { m: Inbound }) {
  const qc = useQueryClient();
  const convs = useQuery({ queryKey: ["conversations"], queryFn: () => api.get<{ id: number; subject: string; provider: string }[]>("/api/conversations") });
  const [cid, setCid] = useState<string>(m.suggestions?.[0]?.conversation_id ? String(m.suggestions[0].conversation_id) : "");
  const assign = useMutation({ mutationFn: () => api.post(`/api/inbound/${m.id}/assign`, { conversation_id: Number(cid) }), onSuccess: () => qc.invalidateQueries() });
  return (
    <div className="flex flex-wrap items-end gap-2 rounded-md bg-amber-50 p-3">
      <Field label={m.suggestions?.length ? "Suggested (same sender has open requests)" : "Assign to a conversation"}>
        <select className={`${inputCls} min-w-[320px]`} value={cid} onChange={(e) => setCid(e.target.value)}>
          <option value="">Choose…</option>
          {m.suggestions?.map((s) => (
            <option key={`s${s.conversation_id}`} value={s.conversation_id}>
              ★ {s.provider} · {s.subject}
            </option>
          ))}
          {convs.data
            ?.filter((c) => !m.suggestions?.some((s) => s.conversation_id === c.id))
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.provider} · {c.subject}
              </option>
            ))}
        </select>
      </Field>
      <Button variant="primary" disabled={!cid} busy={assign.isPending} onClick={() => assign.mutate()}>
        Assign and process
      </Button>
      <ErrorText error={assign.error} />
    </div>
  );
}

function InjectCard({ me }: { me: Me }) {
  const qc = useQueryClient();
  const reqs = useQuery({ queryKey: ["requests"], queryFn: () => api.get<RequestSummary[]>("/api/requests") });
  const [file, setFile] = useState<File | null>(null);
  const [rid, setRid] = useState("");
  const inject = useMutation({
    mutationFn: () => {
      const f = new FormData();
      f.append("file", file!);
      if (rid) f.append("request_id", rid);
      return api.form<{ inbound_id: number; created: boolean }>("/api/dev/inject", f);
    },
    onSuccess: () => qc.invalidateQueries(),
  });
  const sent = reqs.data?.filter((r) => ["waiting_provider", "needs_more", "checking", "handed_back"].includes(r.state)) ?? [];
  return (
    <Card title="Development: inject a raw .eml">
      <p className="mb-3 text-xs text-slate-500">
        Runs the file through the same pipeline as real inbound mail ({me.email_provider} webhook). Pick a request to point the message's To and In-Reply-To at its thread, as a real reply would.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Field label=".eml file">
          <input type="file" accept=".eml,message/rfc822" className={inputCls} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        <Field label="Reply to">
          <select className={inputCls} value={rid} onChange={(e) => setRid(e.target.value)}>
            <option value="">Leave headers as they are</option>
            {sent.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label}
              </option>
            ))}
          </select>
        </Field>
        <Button variant="primary" disabled={!file} busy={inject.isPending} onClick={() => inject.mutate()}>
          Inject
        </Button>
      </div>
      {inject.data && <p className="mt-2 text-xs text-slate-600">{inject.data.created ? `Received as inbound #${inject.data.inbound_id}.` : `Duplicate of inbound #${inject.data.inbound_id} (same Message-ID), ignored.`}</p>}
      <ErrorText error={inject.error} />
    </Card>
  );
}
