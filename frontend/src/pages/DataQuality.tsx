import { useState } from "react";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import { dateTime, num, pct, titleCase } from "../lib/format";
import {
  Badge,
  Card,
  Empty,
  ErrorState,
  Kpi,
  Loading,
  PageHeader,
  Pagination,
  ScoreRing,
  Stat,
  Table,
} from "../components/ui";

export default function DataQuality() {
  const [reason, setReason] = useState("");
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState("");

  const quality = useApi(
    () => api.quality(undefined, page, 20, reason),
    [page, reason],
    30000,
  );
  const catalogue = useApi(() => api.qualityChecks(), []);

  if (quality.loading && !quality.data)
    return <Loading label="Reading data quality results…" />;
  if (quality.error && !quality.data)
    return <ErrorState message={quality.error} onRetry={quality.reload} />;

  const d = quality.data ?? {};
  const summary = d.summary ?? {};
  const checks: any[] = d.checks ?? [];
  const history: any[] = d.history ?? [];
  const reasons: any[] = d.quarantine_reasons ?? [];
  const quarantine = d.quarantine ?? {};

  const categories: Record<string, string[]> = catalogue.data?.categories ?? {};
  const allowed = category ? categories[category] ?? [] : null;
  const visibleChecks = allowed ? checks.filter((c) => allowed.includes(c.check_name)) : checks;

  const sampleRows: any[] = quarantine.sample ?? [];

  return (
    <div>
      <PageHeader
        title="Data Quality"
        subtitle="16 warehouse assertions, the composite quality score and every quarantined record with its reason."
        source="GET /api/data-quality · /api/data-quality/checks"
        actions={
          <>
            <span className="text-[11px] text-slate-500">run #{summary.evaluated_run ?? "—"}</span>
            <button className="btn-ghost" onClick={quality.reload}>
              Refresh
            </button>
          </>
        }
      />

      <div className="grid gap-3 lg:grid-cols-4">
        <Card className="lg:col-span-1">
          <div className="flex items-center gap-4">
            <ScoreRing score={d.score} />
            <div>
              <p className="text-sm font-semibold text-white">
                {Number(d.score ?? 0) >= 95 ? "Healthy warehouse" : "Attention required"}
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
                {summary.scoring ?? "score = (0.6 + 0.4 x pass_rate) x 100"}
              </p>
            </div>
          </div>
        </Card>
        <div className="grid grid-cols-2 gap-3 lg:col-span-3 lg:grid-cols-4">
          <Kpi label="Checks" value={num(summary.checks_total)} hint="assertions executed" />
          <Kpi
            label="Passed"
            value={num(summary.checks_passed)}
            tone="good"
            hint="no rows failed"
          />
          <Kpi
            label="Failed"
            value={num(summary.checks_failed)}
            tone={Number(summary.checks_failed ?? 0) > 0 ? "bad" : "neutral"}
            hint={`${num(summary.checks_warned)} warnings`}
          />
          <Kpi
            label="Quarantined"
            value={num(summary.quarantined_total)}
            tone="warn"
            hint="never reach the warehouse"
          />
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <Card
          title="Check results"
          subtitle="Ordered failures first, then by check name"
          className="lg:col-span-2"
          bodyClass=""
          actions={
            <select
              className="input text-xs"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="">all categories</option>
              {Object.keys(categories).map((c) => (
                <option key={c} value={c}>
                  {titleCase(c)} ({categories[c].length})
                </option>
              ))}
            </select>
          }
        >
          <Table
            columns={[
              {
                key: "check_name",
                label: "Check",
                render: (r) => (
                  <div>
                    <code className="text-[11px] text-slate-200">{r.check_name}</code>
                    <p className="mt-0.5 text-[10px] text-slate-500">{r.entity}</p>
                  </div>
                ),
              },
              {
                key: "status",
                label: "Status",
                render: (r) => <Badge value={r.status} />,
              },
              {
                key: "metric",
                label: "Metric",
                align: "right",
                render: (r) => num(r.metric),
              },
              {
                key: "threshold",
                label: "Limit",
                align: "right",
                render: (r) => num(r.threshold),
              },
              {
                key: "rows_failed",
                label: "Rows failed",
                align: "right",
                render: (r) => (
                  <span className={Number(r.rows_failed ?? 0) > 0 ? "text-rose-300" : ""}>
                    {num(r.rows_failed)}
                  </span>
                ),
              },
              {
                key: "message",
                label: "Assertion",
                render: (r) => (
                  <span className="text-[11px] text-slate-400">{r.message ?? "—"}</span>
                ),
              },
            ]}
            rows={visibleChecks}
            empty="No checks recorded for this run."
          />
        </Card>

        <Card title="Score history" subtitle="Last 20 evaluated runs" bodyClass="">
          <Table
            columns={[
              { key: "run_id", label: "Run", align: "right", render: (r) => `#${r.run_id}` },
              {
                key: "passed",
                label: "Pass / Total",
                align: "right",
                render: (r) => `${r.passed}/${r.checks}`,
              },
              {
                key: "failed",
                label: "Failed",
                align: "right",
                render: (r) => (
                  <span className={Number(r.failed ?? 0) > 0 ? "text-rose-300" : ""}>
                    {num(r.failed)}
                  </span>
                ),
              },
              {
                key: "rows_failed",
                label: "Rows",
                align: "right",
                render: (r) => num(r.rows_failed),
              },
              {
                key: "evaluated_at",
                label: "Evaluated",
                render: (r) => (
                  <span className="text-[11px]">{dateTime(r.evaluated_at)}</span>
                ),
              },
            ]}
            rows={history}
            empty="No quality runs yet."
          />
        </Card>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <Card
          title="Quarantine reasons"
          subtitle="Click a reason to filter the record sample"
          className="lg:col-span-1"
          bodyClass=""
        >
          <Table
            columns={[
              {
                key: "reason",
                label: "Reason",
                render: (r) => (
                  <button
                    className={`text-left text-[11px] ${
                      reason === r.reason ? "text-brand-400" : "text-slate-300 hover:text-white"
                    }`}
                    onClick={() => {
                      setReason(reason === r.reason ? "" : r.reason);
                      setPage(1);
                    }}
                  >
                    {r.reason}
                    <span className="ml-1 text-slate-500">· {r.entity}</span>
                  </button>
                ),
              },
              {
                key: "severity",
                label: "Sev",
                render: (r) => <Badge value={r.severity} />,
              },
              { key: "records", label: "Records", align: "right", render: (r) => num(r.records) },
            ]}
            rows={reasons}
            empty="Quarantine is empty."
          />
        </Card>

        <Card
          title="Quarantined record sample"
          subtitle={
            reason
              ? `filtered by reason = ${reason}`
              : summary.enforced ?? "error-severity rows are rejected"
          }
          className="lg:col-span-2"
          bodyClass=""
          actions={
            reason ? (
              <button className="btn-ghost text-xs" onClick={() => { setReason(""); setPage(1); }}>
                Clear filter
              </button>
            ) : undefined
          }
        >
          {sampleRows.length === 0 ? (
            <Empty label="No quarantined rows for this filter." />
          ) : (
            <>
              <Table
                columns={[
                  { key: "id", label: "ID", align: "right", render: (r) => num(r.id) },
                  { key: "run_id", label: "Run", align: "right", render: (r) => `#${r.run_id}` },
                  { key: "entity", label: "Entity" },
                  { key: "record_id", label: "Record", render: (r) => <code className="text-[11px]">{r.record_id}</code> },
                  {
                    key: "reason",
                    label: "Reason",
                    render: (r) => <span className="text-[11px] text-amber-200/90">{r.reason}</span>,
                  },
                  {
                    key: "payload_preview",
                    label: "Payload",
                    render: (r) => (
                      <code className="text-[10px] text-slate-500">
                        {String(r.payload_preview ?? "").slice(0, 70)}
                      </code>
                    ),
                  },
                ]}
                rows={sampleRows}
              />
              <Pagination
                page={quarantine.page ?? 1}
                pages={quarantine.pages ?? 1}
                total={quarantine.filtered ?? 0}
                onPage={(p) => setPage(p)}
              />
            </>
          )}
        </Card>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
        <Stat label="Total quarantined" value={num(quarantine.total)} />
        <Stat label="Filtered" value={num(quarantine.filtered)} />
        <Stat label="Checks catalogued" value={num(catalogue.data?.implemented_checks)} />
        <Stat
          label="Pass rate"
          value={pct(
            summary.checks_total
              ? (Number(summary.checks_passed ?? 0) / Number(summary.checks_total)) * 100
              : null,
          )}
        />
      </div>
    </div>
  );
}
