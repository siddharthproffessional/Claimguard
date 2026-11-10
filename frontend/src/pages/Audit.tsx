import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useLiveQuery } from "@/hooks/useLive";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { AuditEvent } from "@/types";

const VIEWS: [string, string, Record<string, string>][] = [
  ["all", "All events", {}],
  ["changes", "Claim changes", { event_type: "correction_approved" }],
  ["human", "Human decisions", { actor_type: "human" }],
  ["disagree", "Model disagreements", { event_type: "model_disagreement" }],
  ["conflict", "Agent conflicts", { event_type: "conflict_detected" }],
  ["validation", "Validation runs", { event_type: "validation_run" }],
  ["decisions", "Agent decisions", { event_type: "assessment_completed" }],
  ["failures", "AI provider failures", { event_type: "ai_provider_failure" }],
];
const TONE: Record<string, any> = { human: "teal", agent: "sky", model: "violet", system: "slate" };

export default function Audit() {
  const [view, setView] = useState("all");
  const [claim, setClaim] = useState("");
  const params = { ...VIEWS.find((v) => v[0] === view)![2], ...(claim ? { claim_id: claim } : {}), limit: "500" };
  const { data } = useLiveQuery(() => api.audit(params), [view, claim], 2500);
  return (
    <div>
      <PageHeader title="Audit & Governance" sub="Append-only record of claim changes, agent decisions, human approvals, model disagreements and validation runs, with timestamps and evidence." />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {VIEWS.map(([k, l]) => (
          <button key={k} onClick={() => setView(k)} className={cn("rounded-full border px-3 py-1 text-xs", view === k ? "border-navy-900 bg-navy-900 text-white" : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50")}>{l}</button>
        ))}
        <input value={claim} onChange={(e) => setClaim(e.target.value.toUpperCase())} placeholder="Claim ID"
          className="ml-auto h-8 w-40 rounded-md border border-slate-300 px-2.5 text-xs outline-none focus:border-accent" />
      </div>
      <Card className="overflow-hidden">
        <div className="max-h-[calc(100vh-230px)] overflow-y-auto">
          {(data as AuditEvent[] | null ?? []).map((e) => <Row key={e.id} e={e} />)}
          {data && !data.length && <div className="p-6 text-sm text-slate-500">No events match.</div>}
        </div>
      </Card>
    </div>
  );
}

function Row({ e }: { e: AuditEvent }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-slate-100 text-sm">
      <button onClick={() => setOpen(!open)} className="flex w-full items-start gap-3 px-5 py-2.5 text-left hover:bg-slate-50">
        <ChevronRight className={cn("mt-0.5 h-4 w-4 shrink-0 text-slate-400 transition", open && "rotate-90")} />
        <span className="w-36 shrink-0 font-mono text-[11px] text-slate-400">{new Date(e.ts).toLocaleString()}</span>
        <Badge tone={TONE[e.actor_type] ?? "slate"} className="w-16 justify-center">{e.actor_type}</Badge>
        <span className="w-44 shrink-0 truncate text-xs font-medium text-slate-700">{e.event_type.replace(/_/g, " ")}</span>
        <span className="min-w-0 flex-1 text-slate-600">{e.summary}</span>
        {e.claim_id && <Link to={`/claims/${e.claim_id}`} onClick={(ev) => ev.stopPropagation()} className="font-mono text-xs text-accent-ink hover:underline">{e.claim_id}</Link>}
        <span className="w-28 shrink-0 truncate text-right text-xs text-slate-400">{e.actor}</span>
      </button>
      {open && <pre className="mx-5 mb-3 max-h-80 overflow-auto rounded bg-slate-50 p-3 font-mono text-[11px] text-slate-700">{JSON.stringify(e.details, null, 2)}</pre>}
    </div>
  );
}
