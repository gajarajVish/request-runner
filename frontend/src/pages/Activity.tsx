import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, fmtTime, type AuditEntry, type Outbound } from "../api";
import { OutboundView } from "../components/Mail";
import { Badge, Tabs } from "../components/ui";
import { AuditDetail } from "./Request";

export function ActivityPage() {
  const [tab, setTab] = useState<"audit" | "sent">("audit");
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.get<AuditEntry[]>("/api/audit"), enabled: tab === "audit" });
  const sent = useQuery({ queryKey: ["messages"], queryFn: () => api.get<Outbound[]>("/api/messages"), enabled: tab === "sent" });
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Activity</h1>
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "audit", label: "Audit log" },
          { id: "sent", label: "Outgoing email" },
        ]}
      />
      {tab === "audit" && (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-xs">
            <tbody className="divide-y divide-slate-100">
              {audit.data?.map((a) => (
                <tr key={a.id} className="align-top">
                  <td className="whitespace-nowrap px-3 py-1.5 text-slate-400">{fmtTime(a.at)}</td>
                  <td className="px-3 py-1.5">
                    <Badge tone={a.actor === "requester" ? "blue" : a.actor === "provider" ? "amber" : a.actor === "agent" ? "violet" : "slate"}>{a.actor}</Badge>
                  </td>
                  <td className="whitespace-nowrap px-3 py-1.5">
                    {a.request_id ? (
                      <Link to={`/requests/${a.request_id}`} className="text-brand-700 hover:underline">
                        #{a.request_id}
                      </Link>
                    ) : (
                      ""
                    )}
                  </td>
                  <td className="px-3 py-1.5">
                    <span className="font-medium text-slate-700">{a.action.replace(/_/g, " ")}</span>
                    {a.actor_detail && <span className="text-slate-400"> · {a.actor_detail}</span>}
                    <AuditDetail d={a.detail} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "sent" && <div className="space-y-3">{sent.data?.map((m) => <OutboundView key={m.id} m={m} />)}</div>}
    </div>
  );
}
