/** Formatting helpers shared by every page. */

export const num = (v: unknown, digits = 0): string => {
  const n = typeof v === "number" ? v : Number(v);
  if (v === null || v === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

export const money = (v: unknown, digits = 0): string => {
  const n = typeof v === "number" ? v : Number(v);
  if (v === null || v === undefined || Number.isNaN(n)) return "—";
  return `$${n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
};

export const compact = (v: unknown): string => {
  const n = typeof v === "number" ? v : Number(v);
  if (v === null || v === undefined || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(n);
};

export const pct = (v: unknown, digits = 1): string => {
  const n = typeof v === "number" ? v : Number(v);
  if (v === null || v === undefined || Number.isNaN(n)) return "—";
  return `${n.toFixed(digits)}%`;
};

export const shortDate = (v: unknown): string => {
  if (!v) return "—";
  const d = new Date(String(v));
  if (Number.isNaN(d.getTime())) return String(v).slice(0, 10);
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "2-digit",
  });
};

export const dateTime = (v: unknown): string => {
  if (!v) return "—";
  const raw = String(v);
  const d = new Date(raw.includes("Z") || raw.includes("+") ? raw : `${raw}Z`);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export const duration = (v: unknown): string => {
  const n = typeof v === "number" ? v : Number(v);
  if (v === null || v === undefined || Number.isNaN(n)) return "—";
  if (n < 60) return `${n.toFixed(1)}s`;
  const m = Math.floor(n / 60);
  const s = Math.round(n % 60);
  return `${m}m ${s}s`;
};

export const ago = (v: unknown): string => {
  if (!v) return "—";
  const raw = String(v);
  const d = new Date(raw.includes("Z") || raw.includes("+") ? raw : `${raw}Z`);
  if (Number.isNaN(d.getTime())) return "—";
  const diff = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
};

export const titleCase = (v: unknown): string =>
  String(v ?? "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

export const statusTone = (status: unknown): string => {
  const s = String(status ?? "").toLowerCase();
  if (["success", "pass", "ok", "up", "current", "healthy"].includes(s))
    return "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30";
  if (["running", "queued", "started", "retry"].includes(s))
    return "bg-sky-500/15 text-sky-300 border border-sky-500/30";
  if (["fail", "failed", "error", "down", "quarantined"].includes(s))
    return "bg-rose-500/15 text-rose-300 border border-rose-500/30";
  if (["warning", "warn", "stale", "partial"].includes(s))
    return "bg-amber-500/15 text-amber-300 border border-amber-500/30";
  return "bg-slate-500/15 text-slate-300 border border-slate-500/30";
};

export const CHART_COLORS = [
  "#38bdf8",
  "#34d399",
  "#fbbf24",
  "#f472b6",
  "#a78bfa",
  "#fb923c",
  "#22d3ee",
  "#4ade80",
  "#f87171",
  "#c084fc",
];
