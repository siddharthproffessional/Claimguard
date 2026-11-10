import { ArrowRight, Check, Pencil, X } from "lucide-react";
import { useState } from "react";
import { AgentIcon, StatusBadge, agentName } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, val } from "@/lib/utils";
import { api } from "@/services/api";
import type { Proposal } from "@/types";

const ROLE_LABEL: Record<string, string> = { billing_operator: "Billing operator", certified_coder: "Certified coder", supervisor: "Supervisor" };

export function CorrectionCard({ p, onDone, compact = false, initialResult = null }:
  { p: Proposal; onDone?: (r: any) => void; compact?: boolean; initialResult?: any }) {
  const [editing, setEditing] = useState(p.proposed_value == null);
  const [text, setText] = useState(p.proposed_value == null ? "" : Array.isArray(p.proposed_value) ? (p.proposed_value as string[]).join(", ") : String(p.proposed_value));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<any>(initialResult);

  const parsed = (): unknown => {
    const t = text.trim();
    if (Array.isArray(p.original_value) || Array.isArray(p.proposed_value)) return t.split(",").map((s) => s.trim()).filter(Boolean);
    if (["total_amount", "amount"].includes(p.field)) return Number(t);
    if (p.field === "units") return parseInt(t, 10);
    return t;
  };
  const act = async (kind: "approve" | "reject") => {
    setBusy(true); setErr(null);
    try {
      const r = kind === "approve"
        ? await api.approve(p.claim_id, p.id, editing ? parsed() : undefined, note || undefined)
        : await api.reject(p.claim_id, p.id, note || undefined);
      const res = { kind, ...r };
      setResult(res); onDone?.(res);
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  const decided = result || p.status !== "pending";

  return (
    <div className={cn("rounded-lg border bg-white", p.status === "invalid" ? "border-rose-200" : "border-slate-200")}>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-2.5">
        <AgentIcon agent={p.agent} className="text-slate-500" />
        <span className="text-xs font-semibold text-slate-800">{agentName(p.agent)} Agent</span>
        <Badge tone="slate" className="font-mono">{p.rule_id}</Badge>
        {!compact && <span className="font-mono text-[11px] text-slate-400">{p.claim_id} · #{p.id}</span>}
        <span className="ml-auto flex items-center gap-1.5">
          <Badge tone={p.requires_role === "certified_coder" ? "violet" : "slate"}>Needs {ROLE_LABEL[p.requires_role] ?? p.requires_role}</Badge>
          {(() => { const st = result ? (result.kind === "approve" ? "approved" : "rejected") : p.status;
            return <Badge tone={st === "approved" ? "teal" : st === "rejected" ? "slate" : st === "invalid" ? "rose" : "amber"}>{st}</Badge>; })()}
        </span>
      </div>
      <div className="grid gap-4 p-4 text-sm md:grid-cols-2">
        <div className="space-y-2.5">
          <Row label="Detected problem">{p.problem}</Row>
          <Row label="Field">{p.field}{p.line_no ? ` (line ${p.line_no})` : ""} · <span className="text-slate-500">{p.op.replace(/_/g, " ")}</span></Row>
          <Row label="Supporting evidence">
            {p.evidence?.length ? (
              <ul className="space-y-1">{p.evidence.map((e, i) => (
                <li key={i} className="text-xs text-slate-600"><span className="font-mono text-[11px] text-slate-500">{e.type}{e.ref ? `:${e.ref}` : ""}</span> — {e.detail}</li>))}
              </ul>) : <span className="text-xs text-rose-600">No evidence on file</span>}
          </Row>
        </div>
        <div className="space-y-2.5">
          <div className="flex items-center gap-2 rounded-md bg-slate-50 p-2.5 font-mono text-xs">
            <span className="min-w-0 flex-1 break-words text-rose-700 line-through decoration-rose-300">{val(p.original_value)}</span>
            <ArrowRight className="h-3.5 w-3.5 shrink-0 text-slate-400" />
            {editing && !decided ? (
              <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Enter corrected value"
                className="min-w-0 flex-1 rounded border border-accent bg-white px-2 py-1 text-slate-900 outline-none" />
            ) : <span className="min-w-0 flex-1 break-words font-semibold text-teal-700">{val(p.proposed_value)}</span>}
          </div>
          <Row label="Confidence / uncertainty">{p.confidence_note}</Row>
          <Row label="Dry-run validation"><span className={p.status === "invalid" ? "text-rose-700" : "text-slate-600"}>{p.validation_note}</span></Row>
        </div>
      </div>
      {!decided && p.status === "pending" && (
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-4 py-3">
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note for the audit trail (optional)"
            className="h-8 min-w-[220px] flex-1 rounded-md border border-slate-300 px-2.5 text-xs outline-none focus:border-accent" />
          {p.proposed_value != null && (
            <Button size="sm" variant="ghost" onClick={() => setEditing(!editing)}><Pencil className="h-3.5 w-3.5" />{editing ? "Use proposed" : "Edit"}</Button>
          )}
          <Button size="sm" variant="danger" onClick={() => act("reject")} disabled={busy}><X className="h-3.5 w-3.5" />Reject</Button>
          <Button size="sm" onClick={() => act("approve")} disabled={busy || (editing && !text.trim())}><Check className="h-3.5 w-3.5" />{editing ? "Approve edited value" : "Approve"}</Button>
        </div>
      )}
      {err && <div className="border-t border-rose-100 bg-rose-50 px-4 py-2 text-xs text-rose-700">Refused: {err}</div>}
      {result?.kind === "approve" && (
        <div className="flex flex-wrap items-center gap-2 border-t border-teal-100 bg-teal-50/60 px-4 py-2.5 text-xs text-slate-700">
          Re-validated as v{result.version}: <StatusBadge status={result.before.status} /> <span className="num">{result.before.readiness_score}</span>
          <ArrowRight className="h-3.5 w-3.5" /> <StatusBadge status={result.after.status} /> <span className="num font-semibold">{result.after.readiness_score}</span>
          {result.remaining_failures.length > 0 && <span className="text-slate-500">· still failing: {result.remaining_failures.join(", ")}</span>}
        </div>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</div><div className="mt-0.5 text-slate-700">{children}</div></div>;
}
