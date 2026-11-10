import {
  Activity, BadgeCheck, Bot, Copy, FileSearch, FileText, Fingerprint, Gavel, Inbox, Network, Scale, ShieldCheck, Stethoscope, Wrench,
} from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { cn, fmtTime } from "@/lib/utils";
import type { ClaimStatus, LiveEvent } from "@/types";

export const AGENTS: Record<string, { name: string; short: string; icon: any }> = {
  orchestrator: { name: "ClaimGuard Orchestrator", short: "Orchestrator", icon: Network },
  intake: { name: "Claim Intake Agent", short: "Intake", icon: Inbox },
  eligibility: { name: "Eligibility Agent", short: "Eligibility", icon: Fingerprint },
  documentation: { name: "Documentation Agent", short: "Documentation", icon: FileText },
  coding: { name: "Medical Coding Agent", short: "Coding", icon: Stethoscope },
  authorization: { name: "Prior Authorization Agent", short: "Authorization", icon: BadgeCheck },
  fraud_duplicate: { name: "Fraud & Duplicate Agent", short: "Fraud & Duplicate", icon: Copy },
  compliance: { name: "Compliance Agent", short: "Compliance", icon: Scale },
  recovery: { name: "Recovery & Optimization Agent", short: "Recovery", icon: Wrench },
  independent_reviewer: { name: "Independent Reviewer (OpenAI)", short: "Independent Review", icon: Gavel },
  validation_engine: { name: "Validation Engine", short: "Validation Engine", icon: ShieldCheck },
};
export const agentName = (k?: string | null) => (k ? AGENTS[k]?.short ?? k : "—");
export const AgentIcon = ({ agent, className }: { agent: string; className?: string }) => {
  const I = AGENTS[agent]?.icon ?? Bot;
  return <I className={cn("h-4 w-4", className)} />;
};

const STATUS: Record<string, { label: string; tone: any }> = {
  READY: { label: "Ready", tone: "teal" },
  REQUIRES_CORRECTION: { label: "Requires correction", tone: "amber" },
  HUMAN_REVIEW: { label: "Human review", tone: "rose" },
  PROCESSING: { label: "Processing", tone: "sky" },
  NEW: { label: "Not analysed", tone: "slate" },
};
export const StatusBadge = ({ status }: { status?: ClaimStatus | string | null }) => {
  const s = STATUS[status ?? "NEW"] ?? { label: status, tone: "slate" };
  return <Badge tone={s.tone}>{s.label}</Badge>;
};
export const STATUS_COLOR: Record<string, string> = {
  READY: "#0d9488", REQUIRES_CORRECTION: "#d97706", HUMAN_REVIEW: "#e11d48", NEW: "#94a3b8", PROCESSING: "#38bdf8",
};

export const LIVE_STATUS: Record<string, { label: string; cls: string; dot: string }> = {
  idle: { label: "Idle", cls: "text-slate-400", dot: "bg-slate-500" },
  working: { label: "Working", cls: "text-teal-300", dot: "bg-teal-400 animate-pulseRing" },
  completed: { label: "Completed", cls: "text-emerald-300", dot: "bg-emerald-400" },
  warning: { label: "Warning", cls: "text-amber-300", dot: "bg-amber-400" },
  conflict_detected: { label: "Conflict detected", cls: "text-fuchsia-300", dot: "bg-fuchsia-400 animate-pulseRing" },
  reassessment: { label: "Reassessment", cls: "text-sky-300", dot: "bg-sky-400 animate-pulseRing" },
  failed: { label: "Failed", cls: "text-rose-300", dot: "bg-rose-500" },
};

export function ScoreRing({ score, size = 72, status }: { score?: number | null; size?: number; status?: string }) {
  const r = size / 2 - 6, c = 2 * Math.PI * r, v = score ?? 0;
  const color = STATUS_COLOR[status ?? ""] ?? "#14b8a6";
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="#e2e8f0" strokeWidth={6} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke={color} strokeWidth={6} fill="none" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} style={{ transition: "stroke-dashoffset .6s" }} />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <span className="num text-lg font-semibold">{score == null ? "—" : Math.round(v)}</span>
      </div>
    </div>
  );
}

export function Stat({ label, value, sub, icon, tone = "slate" }: { label: string; value: ReactNode; sub?: ReactNode; icon?: ReactNode; tone?: string }) {
  const ring: Record<string, string> = { teal: "text-teal-600 bg-teal-50", amber: "text-amber-600 bg-amber-50", rose: "text-rose-600 bg-rose-50",
    slate: "text-slate-600 bg-slate-100", sky: "text-sky-600 bg-sky-50", violet: "text-violet-600 bg-violet-50" };
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</span>
        {icon && <span className={cn("grid h-7 w-7 place-items-center rounded-md", ring[tone])}>{icon}</span>}
      </div>
      <div className="num mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="grid place-items-center rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">{children}</div>;
}

export function PageHeader({ title, sub, right }: { title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {sub && <p className="mt-1 max-w-3xl text-sm text-slate-500">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

export function describeEvent(e: LiveEvent): { agent: string; text: string; tone: string; kind: string } {
  switch (e.type) {
    case "agent_message":
      return { agent: e.sender, kind: e.msg_type.replace(/_/g, " "), tone: e.msg_type.includes("review") || e.msg_type.includes("reassess") ? "sky" : "slate",
        text: `→ ${agentName(e.recipient)}: ${e.content}` };
    case "tool_call":
      return { agent: e.agent, kind: "tool", tone: e.ok ? "slate" : "rose", text: `${e.tool}() ${e.ok ? "" : "FAILED "}· ${e.duration_ms} ms` };
    case "agent_run":
      return { agent: e.agent, kind: e.iteration > 1 ? `run · iteration ${e.iteration}` : "run", tone: e.status === "failed" ? "rose" : e.status === "warning" ? "amber" : "teal",
        text: `${e.status}${e.ai_used ? " · AI" : ""} · ${e.duration_ms} ms${e.summary ? ` — ${e.summary}` : ""}` };
    case "conflict":
      return { agent: e.conflict.agents[0], kind: `conflict ${e.conflict.status}`, tone: "violet", text: e.conflict.resolution || e.conflict.description };
    case "audit":
      return { agent: e.actor_type === "human" ? "human" : e.actor, kind: e.event_type.replace(/_/g, " "),
        tone: e.actor_type === "human" ? "teal" : e.event_type.includes("disagreement") || e.event_type.includes("failure") ? "rose" : "slate", text: e.summary };
    default:
      return { agent: "", kind: e.type, tone: "slate", text: JSON.stringify(e) };
  }
}

export function FeedItem({ e, dark = false }: { e: LiveEvent; dark?: boolean }) {
  const d = describeEvent(e);
  const tones: Record<string, string> = dark
    ? { slate: "text-slate-400", sky: "text-sky-300", teal: "text-teal-300", amber: "text-amber-300", rose: "text-rose-300", violet: "text-fuchsia-300" }
    : { slate: "text-slate-500", sky: "text-sky-700", teal: "text-teal-700", amber: "text-amber-700", rose: "text-rose-700", violet: "text-violet-700" };
  return (
    <div className={cn("feed-enter flex gap-2.5 border-b px-3 py-2 text-xs", dark ? "border-navy-800" : "border-slate-100")}>
      <span className={cn("num w-16 shrink-0 pt-0.5 font-mono text-[10px]", dark ? "text-slate-500" : "text-slate-400")}>{fmtTime(e.ts)}</span>
      <AgentIcon agent={d.agent} className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", dark ? "text-slate-400" : "text-slate-500")} />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2">
          <span className={cn("font-semibold", dark ? "text-slate-200" : "text-slate-800")}>{d.agent === "human" ? "Human" : agentName(d.agent)}</span>
          <span className={cn("uppercase tracking-wide text-[10px] font-semibold", tones[d.tone])}>{d.kind}</span>
          {e.claim_id && <span className={cn("font-mono text-[10px]", dark ? "text-slate-500" : "text-slate-400")}>{e.claim_id}</span>}
        </div>
        <div className={cn("mt-0.5 line-clamp-2 break-words", dark ? "text-slate-400" : "text-slate-600")}>{d.text}</div>
      </div>
    </div>
  );
}
