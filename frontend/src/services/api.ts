const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

let identity = { actor: localStorage.getItem("cg_actor") || "dana.billing", role: localStorage.getItem("cg_role") || "billing_operator" };
export const getIdentity = () => identity;
export const setIdentity = (actor: string, role: string) => {
  identity = { actor, role };
  localStorage.setItem("cg_actor", actor); localStorage.setItem("cg_role", role);
};

export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", "X-Actor": identity.actor, "X-Role": identity.role, ...(init.headers || {}) },
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* ignore */ }
    throw new ApiError(r.status, msg);
  }
  return r.json();
}

export const api = {
  health: () => req<any>("/api/health"),
  claims: (params: Record<string, string> = {}) => req<{ total: number; items: any[] }>(`/api/claims?${new URLSearchParams(params)}`),
  claim: (id: string) => req<any>(`/api/claims/${id}`),
  analyze: (id: string, ai_depth?: string) => req<any>(`/api/claims/${id}/analyze`, { method: "POST", body: JSON.stringify({ ai_depth }) }),
  reassess: (id: string, ai_depth?: string) => req<any>(`/api/claims/${id}/reassess`, { method: "POST", body: JSON.stringify({ ai_depth }) }),
  corrections: (id: string) => req<any[]>(`/api/claims/${id}/corrections`),
  pendingCorrections: () => req<any[]>(`/api/corrections?status=pending`),
  approve: (cid: string, pid: number, edited_value?: unknown, note?: string) =>
    req<any>(`/api/claims/${cid}/corrections/${pid}/approve`, { method: "POST", body: JSON.stringify({ edited_value, note }) }),
  reject: (cid: string, pid: number, note?: string) =>
    req<any>(`/api/claims/${cid}/corrections/${pid}/reject`, { method: "POST", body: JSON.stringify({ note }) }),
  runSimulation: (body: { seed: number; ai_depth?: string; operator_mode: string }) =>
    req<any>("/api/simulation/run", { method: "POST", body: JSON.stringify(body) }),
  simulations: () => req<any[]>("/api/simulation"),
  simulation: (id: string) => req<any>(`/api/simulation/${id}`),
  loadDemo: (seed: number) => req<any>("/api/demo/load", { method: "POST", body: JSON.stringify({ seed }) }),
  agents: () => req<any[]>("/api/agents"),
  activity: (claim_id?: string) => req<any[]>(`/api/agents/activity?limit=300${claim_id ? `&claim_id=${claim_id}` : ""}`),
  analytics: () => req<any>("/api/analytics"),
  audit: (params: Record<string, string> = {}) => req<any[]>(`/api/audit?${new URLSearchParams(params)}`),
  rules: () => req<any>("/api/rules"),
};

export const apiBase = () => BASE;

export const wsUrl = () => {
  if (BASE) return BASE.replace(/^http/, "ws") + "/ws/claimguard";
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/claimguard`;
};
