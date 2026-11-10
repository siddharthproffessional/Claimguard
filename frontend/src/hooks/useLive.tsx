import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { wsUrl } from "@/services/api";
import type { LiveEvent } from "@/types";

interface LiveState {
  connected: boolean;
  agentStatus: Record<string, { status: string; claim_id: string | null }>;
  feed: LiveEvent[];
  simulation: { simulation_id?: string; phase?: string; processed?: number; total?: number; error?: string } | null;
  tick: number; // bumps (throttled) whenever claim data changed on the server
  counters: { tool_call: number; agent_message: number; agent_run: number; conflict: number };
}
const Ctx = createContext<LiveState | null>(null);
const FEED_TYPES = new Set(["agent_message", "conflict", "audit", "agent_run", "tool_call"]);

export function LiveProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LiveState>({ connected: false, agentStatus: {}, feed: [], simulation: null, tick: 0,
    counters: { tool_call: 0, agent_message: 0, agent_run: 0, conflict: 0 } });
  const pending = useRef<LiveEvent[]>([]);
  const dirty = useRef(false);

  const flush = useCallback(() => {
    const evs = pending.current; pending.current = [];
    if (!evs.length && !dirty.current) return;
    setState((s) => {
      const agentStatus = { ...s.agentStatus };
      let simulation = s.simulation;
      const counters = { ...s.counters };
      const fresh: LiveEvent[] = [];
      for (const e of evs) {
        if (e.type === "agent_status") agentStatus[e.agent] = { status: e.status, claim_id: e.claim_id };
        else if (e.type === "simulation") simulation = { ...simulation, ...e };
        if (e.type in counters) (counters as any)[e.type] += 1;
        if (FEED_TYPES.has(e.type)) fresh.push(e);
      }
      const tick = dirty.current ? s.tick + 1 : s.tick;
      dirty.current = false;
      return { ...s, agentStatus, simulation, counters, tick, feed: [...fresh.reverse(), ...s.feed].slice(0, 400) };
    });
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null; let closed = false; let retry: number | undefined;
    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => setState((s) => ({ ...s, connected: true }));
      ws.onclose = () => { setState((s) => ({ ...s, connected: false })); if (!closed) retry = window.setTimeout(connect, 1500); };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data);
        if (msg.type === "hello") {
          const agentStatus: LiveState["agentStatus"] = {};
          for (const a of msg.agent_status) agentStatus[a.agent] = { status: a.status, claim_id: a.claim_id };
          setState((s) => ({ ...s, agentStatus, feed: msg.recent.filter((e: LiveEvent) => FEED_TYPES.has(e.type)).reverse().slice(0, 200) }));
          return;
        }
        for (const e of msg.events as LiveEvent[]) {
          pending.current.push(e);
          if (["claim_status", "dataset_loaded", "simulation"].includes(e.type)) dirty.current = true;
        }
      };
    };
    connect();
    const iv = window.setInterval(flush, 250);
    return () => { closed = true; window.clearTimeout(retry); window.clearInterval(iv); ws?.close(); };
  }, [flush]);

  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}

export function useLive() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLive outside provider");
  return v;
}

/** Fetch data and refetch (at most once per `minGapMs`) whenever the server reports changes. */
export function useLiveQuery<T>(fn: () => Promise<T>, deps: unknown[] = [], minGapMs = 1200) {
  const { tick } = useLive();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const last = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  const load = useCallback(() => {
    last.current = Date.now();
    fn().then((d) => { setData(d); setError(null); }).catch((e) => setError(String(e.message || e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (tick === 0) return;
    const wait = Math.max(0, minGapMs - (Date.now() - last.current));
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(load, wait);
    return () => window.clearTimeout(timer.current);
  }, [tick, load, minGapMs]);
  return { data, error, reload: load, setData };
}
