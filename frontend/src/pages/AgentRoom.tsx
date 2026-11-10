import { useMemo, useState } from "react";
import { AGENTS, AgentIcon, Empty, FeedItem, LIVE_STATUS, PageHeader } from "@/components/shared";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useLive, useLiveQuery } from "@/hooks/useLive";
import { cn, fmtMs } from "@/lib/utils";
import { api } from "@/services/api";
import type { AgentInfo, LiveEvent } from "@/types";

const KINDS = [["all", "All"], ["agent_message", "Messages"], ["tool_call", "Tool calls"], ["agent_run", "Runs"], ["conflict", "Conflicts"], ["audit", "Decisions"]];

export default function AgentRoom() {
  const live = useLive();
  const { data: agents } = useLiveQuery(api.agents, [], 2000);
  const [kind, setKind] = useState("all");
  const [agent, setAgent] = useState<string | null>(null);
  const [claim, setClaim] = useState("");
  const { data: history } = useLiveQuery(() => (claim ? api.activity(claim) : Promise.resolve(null)), [claim], 2000);

  const feed = useMemo(() => {
    let f: LiveEvent[] = live.feed;
    if (claim && history) {
      f = (history as any[]).map((h, i) => ({
        seq: -i, ts: h.ts, claim_id: h.claim_id,
        ...(h.kind === "message" ? { type: "agent_message", sender: h.agent, recipient: h.to, msg_type: h.type, content: h.text }
          : h.kind === "tool" ? { type: "tool_call", agent: h.agent, tool: h.type, ok: h.ok, duration_ms: h.duration_ms }
          : { type: "agent_run", agent: h.agent, status: h.type, iteration: h.iteration, ai_used: h.ai_used, duration_ms: h.duration_ms, summary: h.text }),
      })) as LiveEvent[];
    }
    return f.filter((e) => (kind === "all" || e.type === kind) &&
      (!agent || e.agent === agent || e.sender === agent || e.recipient === agent || e.conflict?.agents?.includes(agent) || e.actor === agent));
  }, [live.feed, history, claim, kind, agent]);

  return (
    <div>
      <PageHeader title="Agent Control Room" sub="Eight specialist agents and the orchestrator. Status, counts and timings come from persisted agent runs and tool invocations." />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {(agents as AgentInfo[] | null ?? []).map((a) => {
          const st = live.agentStatus[a.key]?.status ?? a.live?.status ?? "idle";
          const s = LIVE_STATUS[st] ?? LIVE_STATUS.idle;
          return (
            <button key={a.key} onClick={() => setAgent(agent === a.key ? null : a.key)}
              className={cn("rounded-xl border bg-navy-900 p-4 text-left text-slate-300 transition", agent === a.key ? "border-accent ring-2 ring-accent/30" : "border-navy-800 hover:border-navy-600")}>
              <div className="flex items-start justify-between">
                <div className="grid h-8 w-8 place-items-center rounded-md bg-navy-800"><AgentIcon agent={a.key} className="text-accent" /></div>
                <span className={cn("flex items-center gap-1.5 text-[11px]", s.cls)}><span className={cn("h-2 w-2 rounded-full", s.dot)} />{s.label}</span>
              </div>
              <div className="mt-3 text-sm font-semibold text-white">{a.name}</div>
              <div className="mt-1 line-clamp-3 text-[11px] leading-snug text-slate-400">{a.responsibility}</div>
              <div className="mt-3 grid grid-cols-3 gap-1 text-center text-[10px] text-slate-500">
                <div><div className="num text-sm font-semibold text-slate-100">{a.runs}</div>runs</div>
                <div><div className="num text-sm font-semibold text-slate-100">{a.tool_calls}</div>tool calls</div>
                <div><div className="num text-sm font-semibold text-slate-100">{fmtMs(a.avg_ms)}</div>avg</div>
              </div>
              <div className="mt-2 flex flex-wrap gap-x-3 text-[10px] text-slate-500">
                <span>reassessed {a.reassessments}</span><span>AI runs {a.ai_runs}</span><span className={a.failures ? "text-rose-400" : ""}>failed {a.failures}</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">{a.tools.slice(0, 4).map((t) => <span key={t} className="rounded bg-navy-800 px-1.5 py-0.5 font-mono text-[9.5px] text-slate-400">{t}</span>)}</div>
            </button>
          );
        })}
      </div>

      <Card className="mt-6">
        <CardHeader className="flex-wrap">
          <CardTitle>Chronological activity {agent && <span className="font-normal text-slate-500">· {AGENTS[agent]?.name}</span>}</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <input value={claim} onChange={(e) => setClaim(e.target.value.toUpperCase())} placeholder="Filter by claim, e.g. CLM-0007"
              className="h-8 w-56 rounded-md border border-slate-300 px-2.5 text-xs outline-none focus:border-accent" />
            <div className="flex rounded-md border border-slate-300 p-0.5">
              {KINDS.map(([v, l]) => <button key={v} onClick={() => setKind(v)} className={cn("rounded px-2.5 py-1 text-xs", kind === v ? "bg-navy-900 text-white" : "text-slate-600 hover:bg-slate-100")}>{l}</button>)}
            </div>
          </div>
        </CardHeader>
        <div className="max-h-[560px] overflow-y-auto">
          {feed.slice(0, 300).map((e) => <FeedItem key={`${e.seq}-${e.ts}`} e={e} />)}
          {!feed.length && <div className="p-5"><Empty>{claim ? "No recorded activity for that claim." : "No live activity in this session yet. Start Operation Zero Rejection or analyse a claim."}</Empty></div>}
        </div>
      </Card>
    </div>
  );
}
