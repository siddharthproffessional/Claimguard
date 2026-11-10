import { BarChart3, Bot, ClipboardCheck, FileStack, LayoutDashboard, ScrollText, ShieldCheck, Wifi, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useLive } from "@/hooks/useLive";
import { cn } from "@/lib/utils";
import { api, getIdentity, setIdentity } from "@/services/api";

const NAV = [
  { to: "/", label: "Command Centre", icon: LayoutDashboard, end: true },
  { to: "/claims", label: "Claims", icon: FileStack },
  { to: "/agents", label: "Agent Control Room", icon: Bot },
  { to: "/corrections", label: "Correction Workspace", icon: ClipboardCheck },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/audit", label: "Audit & Governance", icon: ScrollText },
];
const ROLES = [
  ["viewer", "Viewer (read only)"], ["billing_operator", "Billing operator"], ["certified_coder", "Certified coder"], ["supervisor", "Supervisor"],
];

export default function Layout() {
  const { connected } = useLive();
  const [id, setId] = useState(getIdentity());
  const [health, setHealth] = useState<any>(null);
  useEffect(() => { api.health().then(setHealth).catch(() => setHealth(null)); }, [connected]);
  const update = (actor: string, role: string) => { setIdentity(actor, role); setId({ actor, role }); };

  return (
    <div className="flex min-h-screen">
      <div className="w-64 shrink-0 bg-navy-950">
      <aside className="sticky top-0 flex h-screen w-64 flex-col text-slate-300">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-accent/15 ring-1 ring-accent/40"><ShieldCheck className="h-5 w-5 text-accent" /></div>
          <div>
            <div className="text-[15px] font-semibold tracking-tight text-white">ClaimGuard</div>
            <div className="text-[10.5px] leading-tight text-slate-400">Prevent the rejection before<br />the claim is submitted.</div>
          </div>
        </div>
        <nav className="mt-2 flex-1 space-y-0.5 px-3">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}
              className={({ isActive }) => cn("flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                isActive ? "bg-navy-800 text-white" : "text-slate-400 hover:bg-navy-900 hover:text-slate-200")}>
              {({ isActive }) => (<><n.icon className={cn("h-4 w-4", isActive && "text-accent")} />{n.label}</>)}
            </NavLink>
          ))}
        </nav>
        <div className="space-y-3 border-t border-navy-800 p-4 text-xs">
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Signed in as (demo)</label>
            <input value={id.actor} onChange={(e) => update(e.target.value, id.role)}
              className="w-full rounded border border-navy-700 bg-navy-900 px-2 py-1.5 text-slate-200 outline-none focus:border-accent" />
            <select value={id.role} onChange={(e) => update(id.actor, e.target.value)}
              className="mt-1.5 w-full rounded border border-navy-700 bg-navy-900 px-2 py-1.5 text-slate-200 outline-none focus:border-accent">
              {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div className="space-y-1 text-[11px]">
            <div className="flex items-center gap-1.5">{connected ? <Wifi className="h-3 w-3 text-teal-400" /> : <WifiOff className="h-3 w-3 text-rose-400" />}
              {connected ? "Live stream connected" : "Live stream offline"}</div>
            <Provider label="Claude" on={health?.claude_configured} detail={health?.claude_model} />
            <Provider label="OpenAI reviewer" on={health?.openai_configured} detail={health?.openai_model} />
          </div>
          <p className="text-[10px] leading-snug text-slate-500">Synthetic data only. Decision support, not adjudication, coding certification or clinical advice.</p>
        </div>
      </aside>
      </div>
      <main className="min-w-0 flex-1 px-8 py-7"><Outlet /></main>
    </div>
  );
}

function Provider({ label, on, detail }: { label: string; on?: boolean; detail?: string }) {
  return (
    <div className="flex items-center gap-1.5" title={detail || ""}>
      <span className={cn("h-1.5 w-1.5 rounded-full", on ? "bg-teal-400" : "bg-slate-600")} />
      <span>{label}: {on ? "configured" : "not configured"}</span>
    </div>
  );
}
