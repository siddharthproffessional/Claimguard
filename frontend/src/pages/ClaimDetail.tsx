import { AlertCircle, ArrowLeft, Bot, CheckCircle2, ChevronDown, CircleSlash, Gavel, GitCompare, Loader2, MinusCircle, RefreshCw, Sparkles, XCircle } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CorrectionCard } from "@/components/corrections/CorrectionCard";
import { AGENTS, AgentIcon, Empty, ScoreRing, StatusBadge, agentName } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useLiveQuery } from "@/hooks/useLive";
import { cn, fmtMoney, fmtMs, fmtTime, val } from "@/lib/utils";
import { api } from "@/services/api";
import type { Assessment, Proposal, ValidationRow } from "@/types";

const SECTIONS = [
  ["eligibility", "Eligibility"], ["documentation", "Documentation"], ["coding", "Coding"], ["authorization", "Authorization"],
  ["fraud_duplicate", "Duplicate & billing screening"], ["compliance", "Compliance"], ["intake", "Intake"],
];
const DIMS = ["eligibility", "documentation", "coding", "authorization", "billing", "compliance"];

export default function ClaimDetail() {
  const { id = "" } = useParams();
  const { data: c, reload } = useLiveQuery(() => api.claim(id), [id], 1000);
  const { data: props, reload: reloadProps } = useLiveQuery(() => api.corrections(id), [id], 1000);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [depth, setDepth] = useState("");

  const run = async (kind: "analyze" | "reassess") => {
    setBusy(true); setErr(null);
    try { await (kind === "analyze" ? api.analyze(id, depth || undefined) : api.reassess(id, depth || undefined)); reload(); reloadProps(); }
    catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  if (!c) return <div className="text-sm text-slate-500">Loading {id}…</div>;
  const a: Assessment | null = c.assessment;
  const val_: ValidationRow[] = c.validation ?? [];
  const latestRuns: Record<string, any> = {};
  for (const r of c.agent_runs) latestRuns[r.agent] = r;
  const pending = (props ?? []).filter((p: Proposal) => p.status === "pending");
  const decided = (props ?? []).filter((p: Proposal) => p.status !== "pending");

  return (
    <div>
      <Link to="/claims" className="mb-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800"><ArrowLeft className="h-3.5 w-3.5" />Claims</Link>
      <div className="mb-6 flex flex-wrap items-center gap-5 rounded-xl border border-slate-200 bg-white p-5">
        <ScoreRing score={c.readiness_score} status={c.status} size={84} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-mono text-xl font-semibold">{c.id}</h1>
            <StatusBadge status={c.status} />
            <Badge tone="slate">version {c.version}</Badge>
            {a && a.engine_status !== a.status && <Badge tone="violet">rules alone: {a.engine_status.replace("_", " ").toLowerCase()}</Badge>}
          </div>
          <div className="mt-1 text-sm text-slate-500">{c.provider} · {c.payer} · service {c.service_date} · {fmtMoney(c.total_amount)}</div>
          {a && <div className="mt-1.5 text-xs text-slate-500">
            Readiness is an internal administrative indicator, not a probability of approval. {a.passed_checks} checks passed · {a.blocking_issues.length} blocking ·
            {" "}{a.iterations} orchestration iteration(s) · shared state v{a.shared_state_version} · {fmtMs(a.duration_ms)}
          </div>}
        </div>
        <div className="flex items-center gap-2">
          <select value={depth} onChange={(e) => setDepth(e.target.value)} className="h-9 rounded-md border border-slate-300 bg-white px-2 text-xs">
            <option value="">AI depth: server default</option><option value="none">Deterministic only</option><option value="synthesis">Synthesis</option><option value="full">Full</option>
          </select>
          {c.status === "NEW"
            ? <Button onClick={() => run("analyze")} disabled={busy}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />}Analyse claim</Button>
            : <Button variant="dark" onClick={() => run("reassess")} disabled={busy}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}Request reassessment</Button>}
        </div>
        {err && <div className="w-full text-xs text-rose-600">{err}</div>}
      </div>

      {a && a.dimension_scores && (
        <div className="mb-6 grid grid-cols-3 gap-3 md:grid-cols-6">
          {DIMS.map((d) => {
            const v = a.dimension_scores[d] ?? 1;
            return (
              <div key={d} className="rounded-lg border border-slate-200 bg-white p-3">
                <div className="text-[11px] font-medium capitalize text-slate-500">{d}</div>
                <div className="mt-1.5 h-1.5 rounded-full bg-slate-100"><div className={cn("h-full rounded-full", v === 1 ? "bg-teal-500" : v === 0 ? "bg-rose-500" : "bg-amber-500")} style={{ width: `${v * 100}%` }} /></div>
                <div className="num mt-1 text-xs text-slate-600">{Math.round(v * 100)}%</div>
              </div>
            );
          })}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          {!a && <Empty>This claim has not been analysed yet.</Empty>}
          {a && (a.escalations.length > 0 || a.conflicts.length > 0 || a.notes.length > 0) && (
            <Card>
              <CardHeader><CardTitle>Orchestrator: conflicts and escalations</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {a.conflicts.map((x) => (
                  <div key={x.id} className="rounded-lg border border-violet-200 bg-violet-50/50 p-3 text-sm">
                    <div className="flex items-center gap-2"><GitCompare className="h-4 w-4 text-violet-600" />
                      <span className="font-medium">{x.agents.map(agentName).join(" vs ")}</span>
                      <Badge tone={x.status === "resolved" ? "teal" : "rose"}>{x.status}</Badge></div>
                    <p className="mt-1 text-slate-700">{x.description}</p>
                    {x.resolution && <p className="mt-1 text-xs text-slate-500">Resolution: {x.resolution}</p>}
                  </div>
                ))}
                {a.escalations.map((e, i) => (
                  <div key={i} className="flex gap-2 rounded-lg border border-rose-200 bg-rose-50/50 p-3 text-sm">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
                    <div><span className="font-medium">Human review — {e.source.replace(/_/g, " ")}</span> <span className="text-xs text-slate-500">({agentName(e.agent)})</span>
                      <p className="text-slate-700">{e.reason}</p></div>
                  </div>
                ))}
                {a.notes.map((n, i) => <p key={i} className="text-xs text-slate-500">• {n}</p>)}
              </CardContent>
            </Card>
          )}

          {a && SECTIONS.map(([key, title]) => {
            const rules = val_.filter((r) => r.agent === key);
            const run = latestRuns[key];
            const extra = (run?.output?.findings ?? []).filter((f: any) => f.source !== "deterministic");
            if (!rules.length && !run) return null;
            return (
              <Card key={key}>
                <CardHeader>
                  <div className="flex items-center gap-2"><AgentIcon agent={key} className="text-accent-ink" /><CardTitle>{title}</CardTitle>
                    <span className="text-xs text-slate-400">{AGENTS[key]?.name}</span></div>
                  {run && <div className="flex items-center gap-2 text-[11px] text-slate-500">
                    {run.iteration > 1 && <Badge tone="sky">reassessed · iteration {run.iteration}</Badge>}
                    {run.ai_used ? <Badge tone="navy"><Sparkles className="h-3 w-3" />AI reasoning</Badge> : run.ai_note ? <span title={run.ai_note}>tools only</span> : null}
                    <span className="num">{fmtMs(run.duration_ms)}</span></div>}
                </CardHeader>
                <div className="divide-y divide-slate-100">
                  {rules.map((r) => <RuleRow key={r.rule_id} r={r} />)}
                  {extra.map((f: any, i: number) => (
                    <div key={i} className="flex gap-3 px-5 py-3 text-sm">
                      {f.source === "ai" ? <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-violet-600" /> : <Bot className="mt-0.5 h-4 w-4 shrink-0 text-sky-600" />}
                      <div><div className="flex items-center gap-2"><span className="font-mono text-xs text-slate-500">{f.code}</span>
                        <Badge tone={f.source === "ai" ? "violet" : "sky"}>{f.source === "ai" ? "AI recommendation (unverified)" : "agent advisory"}</Badge></div>
                        <p className="mt-0.5 text-slate-700">{f.explanation}</p></div>
                    </div>
                  ))}
                  {run?.output?.uncertainty?.length > 0 && <div className="px-5 py-2.5 text-xs text-slate-500">Uncertainty: {run.output.uncertainty.join(" ")}</div>}
                  {run?.status === "failed" && <div className="px-5 py-2.5 text-xs text-rose-600">Agent failed: {run.error}</div>}
                </div>
              </Card>
            );
          })}

          <Card>
            <CardHeader><CardTitle>Correction proposals</CardTitle><span className="text-xs text-slate-500">Nothing changes the claim until a person approves it.</span></CardHeader>
            <CardContent className="space-y-3">
              {pending.map((p: Proposal) => <CorrectionCard key={p.id} p={p} compact onDone={() => { reload(); reloadProps(); }} />)}
              {decided.map((p: Proposal) => <CorrectionCard key={p.id} p={p} compact />)}
              {!props?.length && <Empty>{a ? "No in-system corrections are available for this claim. Blocking issues need external action or human review." : "Analyse the claim first."}</Empty>}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <AIPanel a={a} />
          <Card>
            <CardHeader><CardTitle>Claim information</CardTitle>{c.version > 1 && <Badge tone="teal">changed since v1</Badge>}</CardHeader>
            <CardContent className="space-y-1.5 text-xs">
              {["control_number", "patient_id", "member_id", "patient_dob", "policy_number", "payer_id", "provider_id", "service_date", "submitted_date",
                "place_of_service", "authorization_number", "total_amount"].map((f) => {
                const cur = c.current[f], orig = c.original?.[f];
                const changed = JSON.stringify(cur) !== JSON.stringify(orig);
                return (
                  <div key={f} className="flex justify-between gap-3">
                    <span className="text-slate-500">{f.replace(/_/g, " ")}</span>
                    <span className="text-right font-mono">
                      {changed && <span className="mr-1.5 text-rose-500 line-through">{val(orig)}</span>}
                      <span className={cn(cur == null && "text-rose-500", changed && "font-semibold text-teal-700")}>{val(cur)}</span>
                    </span>
                  </div>
                );
              })}
              <div className="pt-3">
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">Lines</div>
                {c.current.lines.map((l: any) => (
                  <div key={l.line_no} className="mb-1 rounded bg-slate-50 p-2 font-mono">
                    {l.line_no}. {l.procedure_code} · dx {l.diagnosis_codes.join(", ")} · {l.units} × {l.unit_price} = {l.amount}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Attached documents</CardTitle><span className="text-xs text-slate-500">{c.documents.length}</span></CardHeader>
            <div className="divide-y divide-slate-100">
              {c.documents.map((d: any) => <DocRow key={d.id} d={d} />)}
              {!c.documents.length && <div className="p-4 text-xs text-slate-500">No documents attached.</div>}
            </div>
          </Card>
          <Card>
            <CardHeader><CardTitle>Versions</CardTitle></CardHeader>
            <CardContent className="space-y-1.5 text-xs">
              {c.versions.map((v: any) => <div key={v.version} className="flex justify-between"><span>v{v.version} · {v.reason}</span><span className="text-slate-400">{v.actor}</span></div>)}
            </CardContent>
          </Card>
          <Card className="flex max-h-[520px] flex-col">
            <CardHeader><CardTitle>Agent communication</CardTitle><span className="text-xs text-slate-500">{c.messages.length} messages</span></CardHeader>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {c.messages.map((m: any) => (
                <div key={m.id} className="border-b border-slate-100 px-4 py-2 text-xs">
                  <div className="flex items-center gap-1.5"><span className="font-semibold">{agentName(m.sender)}</span><span className="text-slate-400">→ {agentName(m.recipient)}</span>
                    <span className="ml-auto font-mono text-[10px] text-slate-400">{fmtTime(m.created_at)}</span></div>
                  <div className="text-[10px] uppercase tracking-wide text-slate-400">{m.msg_type.replace(/_/g, " ")}</div>
                  <div className="text-slate-600">{m.content}</div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
      {a && <p className="mt-6 text-xs text-slate-400">{a.disclaimer}</p>}
    </div>
  );
}

function RuleRow({ r }: { r: ValidationRow }) {
  const [open, setOpen] = useState(r.status === "fail");
  const Icon = r.status === "pass" ? CheckCircle2 : r.status === "fail" ? XCircle : r.status === "warning" ? AlertCircle : MinusCircle;
  const color = r.status === "pass" ? "text-teal-600" : r.status === "fail" ? "text-rose-600" : r.status === "warning" ? "text-amber-600" : "text-slate-300";
  return (
    <div className="px-5 py-3 text-sm">
      <button className="flex w-full items-start gap-3 text-left" onClick={() => setOpen(!open)}>
        <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", color)} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-slate-500">{r.rule_id}</span><span className="font-medium text-slate-800">{r.name}</span>
            {r.status === "fail" && <Badge tone={r.severity === "critical" ? "rose" : "amber"}>{r.severity}</Badge>}
            {r.resolution && <Badge tone="slate">{r.resolution.replace("_", " ")}</Badge>}
            <Badge tone="slate" className="ml-auto">verified rule</Badge>
          </div>
          <p className={cn("mt-0.5", r.status === "not_applicable" ? "text-slate-400" : "text-slate-600")}>{r.explanation}</p>
        </div>
        {r.evidence.length > 0 && <ChevronDown className={cn("mt-1 h-4 w-4 text-slate-400 transition", open && "rotate-180")} />}
      </button>
      {open && r.evidence.length > 0 && (
        <div className="ml-7 mt-2 space-y-1 rounded-md bg-slate-50 p-2.5 text-xs">
          {r.evidence.map((e, i) => <div key={i}><span className="font-mono text-slate-500">{e.type}{e.ref ? `:${e.ref}` : ""}</span> — {e.detail}</div>)}
          {r.status === "fail" && <div className="pt-1 font-medium text-slate-700">Next action: {r.next_action}</div>}
        </div>
      )}
    </div>
  );
}

function DocRow({ d }: { d: any }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="px-4 py-2.5 text-xs">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between">
        <span><span className="font-mono">{d.id}</span> · {d.doc_type.replace(/_/g, " ")}</span><ChevronDown className={cn("h-3.5 w-3.5 text-slate-400", open && "rotate-180")} />
      </button>
      {open && <pre className="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-2.5 font-mono text-[11px] text-slate-700">{d.content}</pre>}
    </div>
  );
}

function AIPanel({ a }: { a: Assessment | null }) {
  if (!a) return null;
  const s = a.synthesis, r = a.independent_review;
  const statusLine = (v: string) => v === "not_requested" ? "not requested" : v;
  return (
    <Card className="border-navy-700 bg-navy-900 text-slate-200">
      <CardHeader className="border-navy-800"><CardTitle className="text-white">AI assessment</CardTitle><Badge tone="navy">advisory only</Badge></CardHeader>
      <CardContent className="space-y-4 text-xs">
        <div>
          <div className="mb-1 flex items-center gap-1.5 font-semibold text-white"><Sparkles className="h-3.5 w-3.5 text-accent" />Claude orchestrator synthesis</div>
          <div className="text-[11px] text-slate-400">{statusLine(a.ai.claude)}</div>
          {s ? (<div className="mt-1.5 space-y-1.5">
            <p className="text-slate-300">{s.assessment_summary}</p>
            {s.key_risks.length > 0 && <ul className="list-disc pl-4 text-slate-400">{s.key_risks.map((k, i) => <li key={i}>{k}</li>)}</ul>}
            <p>Recommends: <b>{s.recommended_status}</b>{s.recommended_status !== a.engine_status && <span className="text-fuchsia-300"> (differs from rules — logged)</span>}</p>
            {s.unsupported_items.length > 0 && <p className="text-amber-300">Unsupported: {s.unsupported_items.join("; ")}</p>}
          </div>) : <p className="mt-1 text-slate-500">No synthesis for this assessment.</p>}
        </div>
        <div className="border-t border-navy-800 pt-3">
          <div className="mb-1 flex items-center gap-1.5 font-semibold text-white"><Gavel className="h-3.5 w-3.5 text-accent" />Independent review (OpenAI)</div>
          <div className="text-[11px] text-slate-400">{statusLine(a.ai.openai)}</div>
          {r ? (<div className="mt-1.5 space-y-1.5">
            <p>Verdict: <b className={r.verdict === "concur" ? "text-teal-300" : "text-amber-300"}>{r.verdict}</b> · recommends {r.recommended_status}</p>
            <p className="text-slate-300">{r.rationale}</p>
            {r.challenges.map((c, i) => <p key={i} className="text-amber-200">Challenge — {c.target}: {c.issue}</p>)}
            {r.missing_evidence.length > 0 && <p className="text-slate-400">Missing evidence: {r.missing_evidence.join("; ")}</p>}
          </div>) : <p className="mt-1 flex items-center gap-1 text-slate-500"><CircleSlash className="h-3 w-3" />No independent review for this assessment.</p>}
        </div>
        {a.disagreements.length > 0 && <p className="border-t border-navy-800 pt-3 text-fuchsia-300">{a.disagreements.length} model disagreement(s) preserved in the audit log.</p>}
      </CardContent>
    </Card>
  );
}
