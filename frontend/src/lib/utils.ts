import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
export const fmtMoney = (n?: number | null) => n == null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
export const fmtMs = (ms?: number | null) => ms == null ? "—" : ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms.toFixed(ms < 10 ? 1 : 0)} ms`;
export const fmtTime = (ts?: string | null) => ts ? new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
export const pct = (n?: number | null) => n == null ? "—" : `${Math.round(n * 100)}%`;
export const val = (v: unknown) => v == null || v === "" ? "∅ empty" : Array.isArray(v) ? (v.length ? v.join(", ") : "∅ none") : String(v);
