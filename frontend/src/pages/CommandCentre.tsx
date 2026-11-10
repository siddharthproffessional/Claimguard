import { AlertTriangle, CheckCircle2, Clock, FileStack, Play, RotateCcw, ShieldAlert, Sparkles, UserCheck, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AGENTS, AgentIcon, Empty, FeedItem, LIVE_STATUS, PageHeader, STATUS_COLOR, Stat } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useLive, useLiveQuery } from "@/hooks/useLive";
import { cn, fmtMs } from "@/lib/utils";
import { api } from "@/services/api";

const ORDER = ["orchestrator", "intake", "eligibility", "documentation", "coding", "authorization", "fraud_duplicate", "compliance", "recovery", "independent_reviewer"];

export default function CommandCentre() {
  const live = useLive();
  const { data: a, reload } = useLiveQuery(api.analytics, [], 1500);
  const [health, setHealth] = useState<any>(null);
  const [depth, setDepth] = useState("synthesis");
  const [mode, setMode] = useState("manual");
  const [seed, setSeed] = useState(42);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.health().then((h) => { setHealth(h); if (!h.claude_configured && !h.openai_configured) setDepth("none"); }); }, []);

  const sim = live.simulation;
  const running = busy || (!!sim && !["completed", "failed"].includes(sim.phase ?? "") && !!sim.phase);
  const start = async () => {
    setErr(null); setBusy(true);
    try {
      const r = await api.runSimulation({ seed, ai_depth: depth, operator_mode: mode });
      if (r.status === "failed") setErr(r.error || "Simulation failed");
    } catch (e: any) { setErr(e.message); }
    setBusy(false); reload();
  };
  const reset = async () => { setErr(null); try { await api.loadDemo(seed); reload(); } catch (e: any) { setErr(e.message); } };

  const now = a?.status_now ?? {};
  const init = a?.status_initial ?? {};
  const processed = a?.processed ?? 0;
  const issues = (a?.issues_detected_initial ?? []).reduce((s: number, r: any) => s + r.count, 0);
  const pctDone = sim?.total ? Math.round(((sim.processed ?? 0) / sim.total) * 100) : 0;
  const compare = [
    { name: "Before correction", READY: init.READY ?? 0, REQUIRES_CORRECTION: init.REQUIRES_CORRECTION ?? 0, HUMAN_REVIEW: init.HUMAN_REVIEW ?? 0 },
    { name: "Now", READY: now.READY ?? 0, REQUIRES_CORRECTION: now.REQUIRES_CORRECTION ?? 0, HUMAN_REVIEW: now.HUMAN_REVIEW ?? 0 },
  ];

  return (
    <div>
      <PageHeader title="Command Centre" sub="Every figure on this screen is computed by the backend from the loaded synthetic dataset and the agents' actual execution." />

      <div className="mb-6 overflow-hidden rounded-2xl bg-navy-950 text-white shadow-lg">
        <div className="relative px-7 py-6">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(600px_200px_at_85%_0%,rgba(20,184,166,.18),transparent)]" />
          <div className="relative flex flex-wrap items-end justify-between gap-6">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[.2em] text-accent">Signature scenario</div>
              <h2 className="mt-1 text-2xl font-semibold tracking-tight">Operation Zero Rejection</h2>
              <p className="mt-1 max-w-xl text-sm text-slate-400">
                {a?.claims ?? "…"} synthetic claims from a fictional multi-site provider. Eight specialist agents and the orchestrator investigate each one; the deterministic engine decides readiness.
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3 text-xs">
              <Field label="Seed"><input type="number" value={seed} onChange={(e) => setSeed(+e.target.value)} className="w-20 rounded border border-navy-700 bg-navy-900 px-2 py-1.5" /></Field>
              <Field label="AI depth">
                <select value={depth} onChange={(e) => setDepth(e.target.value)} className="rounded border border-navy-700 bg-navy-900 px-2 py-1.5">
                  <option value="none">Deterministic only</option>
                  <option value="synthesis" disabled={!health?.claude_configured && !health?.openai_configured}>Synthesis (docs + flagged)</option>
                  <option value="full" disabled={!health?.claude_configured && !health?.openai_configured}>Full (every agent)</option>
                </select>
              </Field>
              <Field label="Operator">
                <select value={mode} onChange={(e) => setMode(e.target.value)} className="rounded border border-navy-700 bg-navy-900 px-2 py-1.5">
                  <option value="manual">Manual approvals</option>
                  <option value="simulated_approve">Simulated operator (benchmark)</option>
                </select>
              </Field>
              <Button variant="outline" size="sm" className="border-navy-700 bg-transparent text-slate-300 hover:bg-navy-800" onClick={reset} disabled={running}>
                <RotateCcw className="h-3.5 w-3.5" />Reload data
              </Button>
              <Button size="lg" onClick={start} disabled={running || busy}><Play className="h-4 w-4" />{running ? "Running…" : "Start operation"}</Button>
            </div>
          </div>
          {!health?.claude_configured && !health?.openai_configured && (
            <p className="relative mt-3 text-xs text-amber-300">No AI provider keys are configured on the backend. The run will be deterministic only, and the agents will report that honestly.</p>
          )}
          {err && <p className="relative mt-3 text-xs text-rose-300">{err}</p>}
          {sim?.phase && (
            <div className="relative mt-5">
              <div className="mb-1.5 flex justify-between text-xs text-slate-400">
                <span>{sim.phase === "completed" ? "Completed" : sim.phase === "failed" ? `Failed: ${sim.error}` : sim.phase === "baseline" ? "Running baseline scrubber" :
                  sim.phase === "simulated_operator" ? "Simulated operator applying validated corrections" : `Agents processing claims`}</span>
                <span className="num">{sim.processed ?? 0} / {sim.total ?? 0}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-navy-800">
                <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${pctDone}%` }} />
              </div>
              {sim.simulation_id && sim.phase === "completed" && (
                <Link to="/analytics" className="mt-2 inline-block text-xs text-accent hover:underline">View baseline vs ClaimGuard benchmark →</Link>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-8">
        <Stat label="Claims processed" value={`${processed}/${a?.claims ?? 0}`} icon={<FileStack className="h-4 w-4" />} />
        <Stat label="Ready" value={now.READY ?? 0} tone="teal" icon={<CheckCircle2 className="h-4 w-4" />} sub={`was ${init.READY ?? 0}`} />
        <Stat label="Requires correction" value={now.REQUIRES_CORRECTION ?? 0} tone="amber" icon={<Wrench className="h-4 w-4" />} />
        <Stat label="Human review" value={now.HUMAN_REVIEW ?? 0} tone="rose" icon={<UserCheck className="h-4 w-4" />} />
        <Stat label="High-priority flags" value={a?.high_priority_claims ?? 0} tone="rose" icon={<ShieldAlert className="h-4 w-4" />} sub="claims with a critical failure" />
        <Stat label="Issues detected" value={issues} tone="violet" icon={<AlertTriangle className="h-4 w-4" />} sub="potentially preventable reasons" />
        <Stat label="Issues resolved" value={a?.corrections_applied ?? 0} tone="teal" icon={<Sparkles className="h-4 w-4" />} sub="approved corrections" />
        <Stat label="Avg time / claim" value={fmtMs(a?.avg_claim_ms)} icon={<Clock className="h-4 w-4" />} sub="all agents + validation" />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-5">
        <div className="space-y-6 xl:col-span-3">
          <div className="rounded-2xl bg-navy-900 p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">Live agent status</h3>
              <div className="flex gap-4 text-[11px] text-slate-400">
                <span className="text-slate-500">this session:</span><span><b className="num text-slate-200">{live.counters.agent_run}</b> runs</span>
                <span><b className="num text-slate-200">{live.counters.tool_call}</b> tool calls</span>
                <span><b className="num text-slate-200">{live.counters.agent_message}</b> messages</span>
                <span><b className="num text-slate-200">{live.counters.conflict}</b> conflict events</span>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2.5 md:grid-cols-5">
              {ORDER.map((k) => {
                const st = live.agentStatus[k]?.status ?? "idle";
                const s = LIVE_STATUS[st] ?? LIVE_STATUS.idle;
                return (
                  <div key={k} className={cn("rounded-lg border border-navy-700 bg-navy-800/60 p-3", st !== "idle" && "border-navy-600")}>
                    <div className="flex items-center justify-between">
                      <AgentIcon agent={k} className="text-slate-300" />
                      <span className={cn("h-2 w-2 rounded-full", s.dot)} />
                    </div>
                    <div className="mt-2 text-xs font-medium text-slate-100">{AGENTS[k].short}</div>
                    <div className={cn("text-[11px]", s.cls)}>{s.label}</div>
                    <div className="mt-0.5 h-3.5 font-mono text-[10px] text-slate-500">{st !== "idle" ? live.agentStatus[k]?.claim_id : ""}</div>
                  </div>
                );
              })}
            </div>
            <p className="mt-3 text-[10.5px] text-slate-500">Statuses are pushed from the backend as each agent run starts and finishes. Nothing here is animated client-side.</p>
          </div>

          <Card>
            <CardHeader><CardTitle>Claim readiness: before and after correction</CardTitle><span className="text-xs text-slate-500">Mean readiness {a?.mean_readiness_initial ?? "—"} → {a?.mean_readiness_now ?? "—"}</span></CardHeader>
            <CardContent className="h-56">
              {(init.READY ?? 0) + (init.REQUIRES_CORRECTION ?? 0) + (init.HUMAN_REVIEW ?? 0) === 0 ? <Empty>Start the operation to see results.</Empty> : (
                <ResponsiveContainer>
                  <BarChart data={compare} layout="vertical" margin={{ left: 20 }}>
                    <CartesianGrid horizontal={false} stroke="#f1f5f9" />
                    <XAxis type="number" domain={[0, a?.claims ?? 100]} tick={{ fontSize: 11 }} />
                    <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 12 }} />
                    <Tooltip />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="READY" name="Ready" stackId="s" fill={STATUS_COLOR.READY} />
                    <Bar dataKey="REQUIRES_CORRECTION" name="Requires correction" stackId="s" fill={STATUS_COLOR.REQUIRES_CORRECTION} />
                    <Bar dataKey="HUMAN_REVIEW" name="Human review" stackId="s" fill={STATUS_COLOR.HUMAN_REVIEW} radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="flex max-h-[640px] flex-col xl:col-span-2">
          <CardHeader><CardTitle>Recent activity</CardTitle><Link to="/agents" className="text-xs text-accent-ink hover:underline">Control room →</Link></CardHeader>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {live.feed.filter((e) => e.type !== "tool_call").slice(0, 120).map((e) => <FeedItem key={e.seq} e={e} />)}
            {live.feed.length === 0 && <div className="p-5"><Empty>No activity yet in this session.</Empty></div>}
          </div>
        </Card>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex flex-col gap-1 text-slate-400"><span className="text-[10px] uppercase tracking-wider">{label}</span>{children}</label>;
}
