import { Bar, BarChart, CartesianGrid, LabelList, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Empty, PageHeader, agentName } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useLiveQuery } from "@/hooks/useLive";
import { fmtMs, pct } from "@/lib/utils";
import { api } from "@/services/api";

const BASE = "#6366f1", CG = "#0d9488"; // validated pair (light surface)
const axis = { fontSize: 11, fill: "#64748b" };
const grid = <CartesianGrid vertical={false} stroke="#f1f5f9" />;
const tip = <Tooltip cursor={{ fill: "rgba(148,163,184,.12)" }} contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }} />;
const CAT: Record<string, string> = {
  missing_documentation: "Missing docs", eligibility_mismatch: "Eligibility", authorization_issue: "Authorization", coding_inconsistency: "Coding",
  duplicate_submission: "Duplicates", coverage_problem: "Coverage", conflicting_information: "Conflicting info", billing_inconsistency: "Billing",
  incomplete_fields: "Incomplete fields",
};

export default function Analytics() {
  const { data: a } = useLiveQuery(api.analytics, [], 2500);
  const r = a?.latest_simulation?.results;
  const b = r?.baseline, c = r?.claimguard;
  const headline = b && c ? [
    { m: "Labelled issues detected", Baseline: b.issues_detected, ClaimGuard: c.issues_detected },
    { m: "Claims flagged", Baseline: b.claims_flagged, ClaimGuard: c.claims_flagged },
    { m: "Problem claims passed through", Baseline: b.claims_with_issue_not_flagged, ClaimGuard: c.claims_with_issue_not_flagged },
    { m: "False-positive claims", Baseline: b.false_positive_claims, ClaimGuard: c.false_positive_claims },
  ] : [];
  const cats = b && c ? Object.keys(r.dataset.by_category).map((k) => ({
    cat: CAT[k] ?? k, labelled: r.dataset.by_category[k], Baseline: b.by_category[k]?.detected ?? 0, ClaimGuard: c.by_category[k]?.detected ?? 0,
  })) : [];
  const status = a ? ["READY", "REQUIRES_CORRECTION", "HUMAN_REVIEW"].map((s) => ({ s, label: s === "READY" ? "Ready" : s === "HUMAN_REVIEW" ? "Human review" : "Requires correction",
    Initial: a.status_initial?.[s] ?? 0, Now: a.status_now?.[s] ?? 0 })) : [];

  return (
    <div>
      <PageHeader title="Analytics" sub="Computed from the backend database and the latest saved simulation run. Results describe behaviour on synthetic data only; they are not a measured reduction in real-world rejections." />
      {!r && <div className="mb-6"><Empty>No completed simulation yet. Run Operation Zero Rejection from the Command Centre to produce the baseline comparison.</Empty></div>}

      {r && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <Badge tone="slate">simulation {r.simulation_id}</Badge><Badge tone="slate">seed {r.seed}</Badge>
            <Badge tone="slate">AI depth {c.ai.depth}</Badge><Badge tone="slate">operator: {c.operator_mode.replace("_", " ")}</Badge>
            <span>{r.dataset.claims} claims · {r.dataset.clean} clean · {r.dataset.labelled_issues} labelled issues ({r.dataset.ai_only_issues} only visible in free text)</span>
          </div>
          <div className="mb-6 grid gap-6 xl:grid-cols-5">
            <Card className="xl:col-span-3">
              <CardHeader><CardTitle>Baseline scrubber vs ClaimGuard — same {r.dataset.claims} claims</CardTitle></CardHeader>
              <CardContent className="h-72">
                <ResponsiveContainer>
                  <BarChart data={headline} barGap={2} margin={{ top: 18 }}>
                    {grid}<XAxis dataKey="m" tick={axis} interval={0} /><YAxis tick={axis} allowDecimals={false} />{tip}
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="Baseline" fill={BASE} radius={[4, 4, 0, 0]} maxBarSize={44}><LabelList dataKey="Baseline" position="top" fontSize={11} fill="#334155" /></Bar>
                    <Bar dataKey="ClaimGuard" fill={CG} radius={[4, 4, 0, 0]} maxBarSize={44}><LabelList dataKey="ClaimGuard" position="top" fontSize={11} fill="#334155" /></Bar>
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card className="xl:col-span-2">
              <CardHeader><CardTitle>Side by side</CardTitle></CardHeader>
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-slate-500"><tr><th className="px-5 py-2 font-medium">Measure</th><th className="px-3 py-2 text-right font-medium">Baseline</th><th className="px-5 py-2 text-right font-medium">ClaimGuard</th></tr></thead>
                <tbody className="num">
                  <Tr k="Issue recall (labelled)" b={pct(b.issue_recall)} c={pct(c.issue_recall)} />
                  <Tr k="Issues detected" b={`${b.issues_detected}/${b.labelled_issues}`} c={`${c.issues_detected}/${c.labelled_issues}`} />
                  <Tr k="False-positive claims" b={b.false_positive_claims} c={c.false_positive_claims} />
                  <Tr k="Problem claims passed through" b={b.claims_with_issue_not_flagged} c={c.claims_with_issue_not_flagged} />
                  <Tr k="Correction proposals" b={0} c={`${c.proposals.validated} validated`} />
                  {c.operator_mode === "manual"
                    ? <Tr k="READY now → if all validated fixes approved" b="n/a" c={`${c.status_initial.READY} → ${c.projected_ready_if_all_validated_proposals_approved}`} />
                    : <Tr k="READY before → after simulated approvals" b="n/a" c={`${c.status_initial.READY} → ${c.status_final.READY}`} />}
                  <Tr k={c.operator_mode === "manual" ? "Blocking issues at end of run" : "Unresolved blocking issues"} b="not tracked"
                    c={c.operator_mode === "manual" ? `${c.unresolved_blocking_initial}` : `${c.unresolved_blocking_initial} → ${c.unresolved_blocking_final}`} />
                  <Tr k="Human decisions required" b="n/a" c={c.human_decisions_required} />
                  <Tr k="Conflicts detected / resolved" b="n/a" c={`${c.conflicts.detected} / ${c.conflicts.resolved}`} />
                  <Tr k="Processing time (all claims)" b={fmtMs(b.processing_ms)} c={fmtMs(c.processing_ms)} />
                  <Tr k="Agent runs · tool calls" b="—" c={`${c.agent_runs} · ${c.tool_invocations}`} />
                  <Tr k="AI calls (failures)" b="—" c={`${c.ai.calls} (${c.ai.failures})`} />
                </tbody>
              </table>
            </Card>
          </div>

          <Card className="mb-6">
            <CardHeader><CardTitle>Detection by issue category</CardTitle><span className="text-xs text-slate-500">grey tick = labelled issues in the dataset</span></CardHeader>
            <CardContent className="h-72">
              <ResponsiveContainer>
                <BarChart data={cats} barGap={2}>
                  {grid}<XAxis dataKey="cat" tick={axis} interval={0} /><YAxis tick={axis} allowDecimals={false} />{tip}<Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="labelled" name="Labelled" fill="#cbd5e1" radius={[4, 4, 0, 0]} maxBarSize={28} />
                  <Bar dataKey="Baseline" fill={BASE} radius={[4, 4, 0, 0]} maxBarSize={28} />
                  <Bar dataKey="ClaimGuard" fill={CG} radius={[4, 4, 0, 0]} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </>
      )}

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Claims by status: first assessment vs now</CardTitle></CardHeader>
          <CardContent className="h-[25rem]">
            {!a?.processed ? <Empty>No processed claims.</Empty> : (
              <ResponsiveContainer>
                <BarChart data={status} barGap={2} margin={{ top: 18 }}>
                  {grid}<XAxis dataKey="label" tick={axis} /><YAxis tick={axis} allowDecimals={false} />{tip}<Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="Initial" name="First assessment" fill="#94a3b8" radius={[4, 4, 0, 0]} maxBarSize={40}><LabelList dataKey="Initial" position="top" fontSize={11} /></Bar>
                  <Bar dataKey="Now" fill={CG} radius={[4, 4, 0, 0]} maxBarSize={40}><LabelList dataKey="Now" position="top" fontSize={11} /></Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Most common rejection-risk patterns</CardTitle><span className="text-xs text-slate-500">failed rules at first assessment</span></CardHeader>
          <CardContent className="h-[25rem]">
            {!a?.issues_detected_initial?.length ? <Empty>No issues detected yet.</Empty> : (
              <ResponsiveContainer>
                <BarChart data={a.issues_detected_initial} layout="vertical" margin={{ left: 10 }}>
                  <CartesianGrid horizontal={false} stroke="#f1f5f9" /><XAxis type="number" tick={axis} allowDecimals={false} />
                  <YAxis type="category" dataKey="name" width={210} interval={0} tick={{ fontSize: 10.5, fill: "#475569" }} />{tip}
                  <Bar dataKey="count" name="Claims" fill={CG} radius={[0, 4, 4, 0]} maxBarSize={14}><LabelList dataKey="count" position="right" fontSize={10.5} fill="#334155" /></Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Agent workload</CardTitle><span className="text-xs text-slate-500">mean claim time {fmtMs(a?.avg_claim_ms)}</span></CardHeader>
          <CardContent className="h-64">
            {!a?.agent_workload?.length ? <Empty>No agent runs yet.</Empty> : (
              <ResponsiveContainer>
                <BarChart data={a.agent_workload.map((w: any) => ({ ...w, name: agentName(w.agent) }))} margin={{ bottom: 10 }}>
                  {grid}<XAxis dataKey="name" tick={{ fontSize: 10, fill: "#64748b" }} interval={0} angle={-20} textAnchor="end" height={50} /><YAxis tick={axis} />{tip}
                  <Bar dataKey="runs" name="Runs" fill={CG} radius={[4, 4, 0, 0]} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Benchmark assumptions</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-2 text-xs text-slate-600">{(r?.assumptions ?? []).map((x: string, i: number) => <li key={i} className="flex gap-2"><span className="text-slate-400">{i + 1}.</span>{x}</li>)}</ul>
            {!r && <p className="text-xs text-slate-500">Shown after a simulation run.</p>}
            {a?.escalation_sources && Object.keys(a.escalation_sources).length > 0 && (
              <div className="mt-4 text-xs text-slate-600">Human-review escalations by source: {Object.entries(a.escalation_sources).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}</div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Tr({ k, b, c }: { k: string; b: React.ReactNode; c: React.ReactNode }) {
  return <tr className="border-t border-slate-100"><td className="px-5 py-2 text-slate-600">{k}</td><td className="px-3 py-2 text-right text-slate-700">{b}</td><td className="px-5 py-2 text-right font-semibold text-teal-700">{c}</td></tr>;
}
