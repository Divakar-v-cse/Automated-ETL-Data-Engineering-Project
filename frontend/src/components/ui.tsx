import type { ReactNode } from "react";
import { statusTone, titleCase } from "../lib/format";

export function PageHeader({
  title,
  subtitle,
  actions,
  source,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  source?: string;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-white sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
        {source && (
          <p className="mt-1 font-mono text-[11px] text-slate-500">{source}</p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
    </div>
  );
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = "",
  bodyClass = "card-pad",
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-700/70 px-4 py-3">
          <div>
            {title && (
              <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
            )}
            {subtitle && (
              <p className="mt-0.5 text-[11px] text-slate-500">{subtitle}</p>
            )}
          </div>
          {actions}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function Kpi({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "neutral" | "good" | "bad" | "warn";
}) {
  const ring =
    tone === "good"
      ? "border-emerald-500/25"
      : tone === "bad"
        ? "border-rose-500/25"
        : tone === "warn"
          ? "border-amber-500/25"
          : "border-ink-700";
  return (
    <div className={`card card-pad border ${ring}`}>
      <p className="label">{label}</p>
      <p className="value mt-1">{value}</p>
      {hint && <p className="mt-1 text-[11px] text-slate-500">{hint}</p>}
    </div>
  );
}

export function Badge({ value, text }: { value: unknown; text?: string }) {
  return (
    <span className={`chip ${statusTone(value)}`}>
      {text ?? titleCase(value)}
    </span>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 px-1 py-8 text-sm text-slate-400">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-600 border-t-brand-400" />
      {label}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded-lg border border-rose-500/30 bg-rose-500/5 p-4">
      <p className="text-sm font-medium text-rose-300">
        Backend request failed
      </p>
      <p className="mt-1 font-mono text-xs text-rose-200/80">{message}</p>
      {onRetry && (
        <button className="btn-ghost mt-3 text-xs" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ label = "No rows returned by the warehouse." }) {
  return <p className="py-8 text-center text-sm text-slate-500">{label}</p>;
}

export function Table({
  columns,
  rows,
  empty = "No rows.",
}: {
  columns: { key: string; label: string; render?: (row: any) => ReactNode; align?: "left" | "right" }[];
  rows: any[];
  empty?: string;
}) {
  if (!rows?.length) return <Empty label={empty} />;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-ink-700/70">
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={`th ${c.align === "right" ? "text-right" : ""}`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-800">
          {rows.map((row, i) => (
            <tr key={i} className="hover:bg-ink-850/60">
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`td ${c.align === "right" ? "text-right tabular-nums" : ""}`}
                >
                  {c.render ? c.render(row) : (row[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pagination({
  page,
  pages,
  total,
  onPage,
}: {
  page: number;
  pages: number;
  total: number;
  onPage: (p: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-ink-700/70 px-4 py-3 text-xs text-slate-400">
      <span>
        Page {page} of {Math.max(pages, 1)} · {total.toLocaleString()} rows
      </span>
      <div className="flex gap-2">
        <button
          className="btn-ghost px-2 py-1 text-xs"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          Previous
        </button>
        <button
          className="btn-ghost px-2 py-1 text-xs"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}

export function ScoreRing({ score }: { score: number | null | undefined }) {
  const value = Math.max(0, Math.min(100, Number(score ?? 0)));
  const color =
    value >= 95 ? "#34d399" : value >= 80 ? "#fbbf24" : "#f87171";
  const r = 34;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative h-24 w-24">
      <svg viewBox="0 0 80 80" className="h-24 w-24 -rotate-90">
        <circle cx="40" cy="40" r={r} fill="none" stroke="#1e293b" strokeWidth="8" />
        <circle
          cx="40"
          cy="40"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={`${(value / 100) * c} ${c}`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-lg font-semibold text-white">{value.toFixed(1)}</span>
        <span className="text-[10px] uppercase tracking-wide text-slate-500">score</span>
      </div>
    </div>
  );
}

export function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: ReactNode;
  tone?: string;
}) {
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-850/60 px-3 py-2">
      <p className="label">{label}</p>
      <p className={`mt-0.5 text-lg font-semibold ${tone ?? "text-white"}`}>
        {value}
      </p>
    </div>
  );
}
