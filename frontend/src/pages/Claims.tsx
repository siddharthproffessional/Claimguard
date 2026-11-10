import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader, StatusBadge, agentName } from "@/components/shared";
import { Card } from "@/components/ui/card";
import { useLiveQuery } from "@/hooks/useLive";
import { cn, fmtMoney, fmtTime } from "@/lib/utils";
import { api } from "@/services/api";
import type { ClaimRow } from "@/types";

const FILTERS = [["", "All"], ["READY", "Ready"], ["REQUIRES_CORRECTION", "Requires correction"], ["HUMAN_REVIEW", "Human review"], ["NEW", "Not analysed"]];

export default function Claims() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState<{ k: keyof ClaimRow; dir: 1 | -1 }>({ k: "seq", dir: 1 });
  const { data } = useLiveQuery(() => api.claims({ limit: "1000" }), [], 1500);
  const rows = useMemo(() => {
    let r = (data?.items ?? []) as ClaimRow[];
    if (status) r = r.filter((c) => c.status === status);
    if (q) { const s = q.toLowerCase(); r = r.filter((c) => [c.id, c.patient_id, c.control_number, c.provider, c.payer, ...c.procedures].join(" ").toLowerCase().includes(s)); }
    return [...r].sort((a, b) => ((a[sort.k] ?? -1) > (b[sort.k] ?? -1) ? 1 : -1) * sort.dir);
  }, [data, q, status, sort]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of (data?.items ?? []) as ClaimRow[]) c[r.status] = (c[r.status] ?? 0) + 1;
    return c;
  }, [data]);
  const th = (k: keyof ClaimRow, label: string, cls = "") => (
    <th className={cn("cursor-pointer select-none px-3 py-2.5 font-medium hover:text-slate-900", cls)}
      onClick={() => setSort((s) => ({ k, dir: s.k === k ? (s.dir * -1) as 1 | -1 : 1 }))}>
      {label}{sort.k === k ? (sort.dir === 1 ? " ↑" : " ↓") : ""}
    </th>
  );

  return (
    <div>
      <PageHeader title="Claims Management" sub="Synthetic claims with their current deterministic status. Select a claim to see the full investigation." />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search claim, patient ref, provider, code…"
            className="h-9 w-80 rounded-md border border-slate-300 bg-white pl-8 pr-3 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20" />
        </div>
        <div className="flex rounded-md border border-slate-300 bg-white p-0.5">
          {FILTERS.map(([v, l]) => (
            <button key={v} onClick={() => setStatus(v)} className={cn("rounded px-3 py-1.5 text-xs font-medium", status === v ? "bg-navy-900 text-white" : "text-slate-600 hover:bg-slate-100")}>
              {l}{v ? <span className="num ml-1 opacity-70">{counts[v] ?? 0}</span> : <span className="num ml-1 opacity-70">{data?.total ?? 0}</span>}
            </button>
          ))}
        </div>
      </div>
      <Card className="overflow-hidden">
        <div className="max-h-[calc(100vh-220px)] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50 text-left text-xs text-slate-500 shadow-[0_1px_0_#e2e8f0]">
              <tr>
                {th("id", "Claim ID")}{th("patient_id", "Patient ref")}{th("provider", "Provider")}{th("payer", "Payer")}
                {th("total_amount", "Amount", "text-right")}{th("status", "Status")}{th("readiness_score", "Readiness", "text-right")}
                {th("issue_count", "Issues", "text-right")}{th("assigned_agent", "Assigned agent")}{th("updated_at", "Last updated")}
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} onClick={() => nav(`/claims/${c.id}`)} className="cursor-pointer border-t border-slate-100 hover:bg-teal-50/40">
                  <td className="px-3 py-2.5 font-mono text-xs font-medium text-slate-900">{c.id}{c.version > 1 && <span className="ml-1 text-[10px] text-teal-600">v{c.version}</span>}</td>
                  <td className="px-3 py-2.5 font-mono text-xs text-slate-600">{c.patient_id}</td>
                  <td className="max-w-[200px] truncate px-3 py-2.5 text-slate-700">{c.provider}</td>
                  <td className="max-w-[180px] truncate px-3 py-2.5 text-slate-600">{c.payer?.replace(" (synthetic)", "")}</td>
                  <td className="num px-3 py-2.5 text-right">{fmtMoney(c.total_amount)}</td>
                  <td className="px-3 py-2.5"><StatusBadge status={c.status} /></td>
                  <td className="num px-3 py-2.5 text-right font-medium">{c.readiness_score ?? "—"}</td>
                  <td className={cn("num px-3 py-2.5 text-right", c.issue_count ? "font-semibold text-rose-600" : "text-slate-400")}>{c.issue_count}</td>
                  <td className="px-3 py-2.5 text-xs text-slate-600">{agentName(c.assigned_agent)}</td>
                  <td className="px-3 py-2.5 font-mono text-[11px] text-slate-400">{fmtTime(c.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
