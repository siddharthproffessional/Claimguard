import { useMemo, useState } from "react";
import { CorrectionCard } from "@/components/corrections/CorrectionCard";
import { Empty, PageHeader, agentName } from "@/components/shared";
import { useLiveQuery } from "@/hooks/useLive";
import { cn } from "@/lib/utils";
import { api, getIdentity } from "@/services/api";
import type { Proposal } from "@/types";

export default function Corrections() {
  const { data, reload } = useLiveQuery(api.pendingCorrections, [], 3000);
  const [agent, setAgent] = useState("");
  // decisions made on this page stay visible (with before/after) after the pending list refreshes
  const [decided, setDecided] = useState<{ p: Proposal; r: any }[]>([]);
  const decidedIds = new Set(decided.map((d) => d.p.id));
  const rows = ((data ?? []) as Proposal[]).filter((p) => !decidedIds.has(p.id));
  const agents = useMemo(() => Array.from(new Set(rows.map((r) => r.agent))), [rows]);
  const shown = rows.filter((r) => !agent || r.agent === agent);
  return (
    <div>
      <PageHeader title="Correction Workspace"
        sub={<>Validated correction proposals waiting for a decision. Each one was dry-run through the deterministic engine. Approving creates a new claim version and re-validates it; the original stays intact. You are acting as <b>{getIdentity().actor}</b> ({getIdentity().role.replace("_", " ")}).</>}
        right={<button onClick={reload} className="text-xs text-accent-ink hover:underline">Refresh</button>} />
      <div className="mb-4 flex flex-wrap gap-1.5">
        <Chip on={!agent} onClick={() => setAgent("")}>All ({rows.length})</Chip>
        {agents.map((a) => <Chip key={a} on={agent === a} onClick={() => setAgent(a)}>{agentName(a)} ({rows.filter((r) => r.agent === a).length})</Chip>)}
      </div>
      <div className="space-y-3">
        {decided.map(({ p, r }) => <CorrectionCard key={`d${p.id}`} p={p} initialResult={r} />)}
        {shown.map((p) => <CorrectionCard key={p.id} p={p} onDone={(r) => setDecided((d) => [{ p, r }, ...d])} />)}
        {!shown.length && <Empty>No pending corrections. Run Operation Zero Rejection to generate proposals.</Empty>}
      </div>
    </div>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button onClick={onClick} className={cn("rounded-full border px-3 py-1 text-xs", on ? "border-navy-900 bg-navy-900 text-white" : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50")}>{children}</button>;
}
