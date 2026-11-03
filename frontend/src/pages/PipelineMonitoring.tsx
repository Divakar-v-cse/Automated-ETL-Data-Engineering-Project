import { useState } from "react";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import { ago, dateTime, duration, num, pct } from "../lib/format";
import {
  Badge,
  Card,
  ErrorState,
  Kpi,
  Loading,
  PageHeader,
  Stat,
  Table,
} from "../components/ui";

const DAGS = [
  "daily_etl_pipeline",
  "incremental_ingestion_pipeline",
  "data_quality_pipeline",
  "analytics_pipeline",
  "reporting_pipeline",
];

export default function PipelineMonitoring() {
  const status = useApi(() => api.pipelineStatus(), [], 10000);
  const schedule = useApi(() => api.schedule(), []);
  const [dagId, setDagId] = useState("daily_etl_pipeline");
  const [incremental, setIncremental] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const trigger = async () => {
    setBusy(true);
    setNotice(null);
    setFailure(null);
    try {
      const res = await api.trigger({ dag_id: dagId, incremental, mode: "async" });
      setNotice(`Run ${res.run_id ?? "?"} accepted (${res.status}); polling this page.`);
      status.reload();
    } catch (e: any) {
      setFailure(`${e?.status ?? ""} ${e?.message ?? "trigger failed"}`.trim());
    } finally {
      setBusy(false);
    }
  };

  if (status.loading && !status.data) return <Loading label="Reading pipeline ledger…" />;
  if (status.error && !status.data)
    return <ErrorState message={status.error} onRetry={status.reload} />;

  const d = status.data ?? {};
  const latest = d.latest_run ?? {};
  const health = d.health ?? {};
  const stages: any[] = d.stages ?? [];
  const freshness: any[] = d.freshness ?? [];
  const watermarks: any[] = d.watermarks ?? [];
  const running = Boolean(d.active_run) || d.status === "running";

  return (
    <div>
      <PageHeader
        title="Pipeline Monitoring"
        subtitle="Live execution state of the Airflow-compatible runner, stage timings and source freshness."
        source="GET /api/pipeline/status · /schedule · /watermarks"
        actions={
          <>
            <span className="text-[11px] text-slate-500">
              polled {status.lastUpdated ? ago(status.lastUpdated.toISOString()) : "—"}
            </span>
            <button className="btn-ghost" onClick={status.reload}>
              Refresh
            </button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi
          label="Runner state"
          value={<Badge value={d.status === "never_run" ? "idle" : d.status} />}
          hint={`latest run #${latest.run_id ?? "—"}`}
        />
        <Kpi
          label="Records loaded"
          value={num(latest.records_loaded)}
          hint={`${num(latest.records_extracted)} extracted · ${num(latest.records_rejected)} rejected`}
        />
        <Kpi
          label="Quality score"
          value={pct(latest.quality_score)}
          tone={Number(latest.quality_score ?? 0) >= 95 ? "good" : "warn"}
          hint={`threshold ${health.quality_threshold ?? "—"}`}
        />
        <Kpi
          label="Success rate"
          value={d.success_rate_pct == null ? "—" : pct(d.success_rate_pct)}
          tone={Number(d.success_rate_pct ?? 0) >= 90 ? "good" : "bad"}
          hint={`${health.successful_runs ?? 0}/${health.runs_considered ?? 0} terminal runs`}
        />
      </div>

      {running && (
        <div className="mt-3 rounded-lg border border-sky-500/30 bg-sky-500/5 px-4 py-3 text-sm text-sky-200">
          <span className="mr-2 inline-flex h-2 w-2 animate-pulse rounded-full bg-sky-400" />
          Run #{d.active_run?.run_id} ({d.active_run?.dag_id}) is executing — figures update every 10 s.
        </div>
      )}

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <Card
          title="Trigger a workflow"
          subtitle="POST /api/pipeline/trigger — async, returns 202 and 409 while busy"
          className="lg:col-span-1"
        >
          <div className="space-y-3">
            <label className="block">
              <span className="label">DAG</span>
              <select
                className="input mt-1 w-full"
                value={dagId}
                onChange={(e) => setDagId(e.target.value)}
              >
                {DAGS.map((dag) => (
                  <option key={dag} value={dag}>
                    {dag}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-xs text-slate-300">
              <input
                type="checkbox"
                checked={incremental}
                onChange={(e) => setIncremental(e.target.checked)}
              />
              incremental (watermark window)
            </label>
            <button
              className="btn-primary w-full"
              disabled={busy || running}
              onClick={trigger}
            >
              {busy ? "Submitting…" : running ? "Run in progress" : "Trigger run"}
            </button>
            {notice && (
              <p className="rounded border border-emerald-500/30 bg-emerald-500/5 px-2 py-1.5 text-[11px] text-emerald-300">
                {notice}
              </p>
            )}
            {failure && (
              <p className="rounded border border-rose-500/30 bg-rose-500/5 px-2 py-1.5 font-mono text-[11px] text-rose-300">
                {failure}
              </p>
            )}
          </div>
        </Card>

        <Card
          title="Stage timings — latest run"
          subtitle={`${latest.dag_id ?? "no run"} · ${latest.status ?? "—"} · ${duration(latest.duration_seconds)}`}
          className="lg:col-span-2"
          bodyClass=""
        >
          <Table
            columns={[
              { key: "task_name", label: "Stage" },
              {
                key: "status",
                label: "Status",
                render: (r) => <Badge value={r.status} />,
              },
              { key: "attempt", label: "Try", align: "right" },
              {
                key: "started_at",
                label: "Started",
                render: (r) => <span className="text-xs">{dateTime(r.started_at)}</span>,
              },
              {
                key: "duration_seconds",
                label: "Duration",
                align: "right",
                render: (r) => duration(r.duration_seconds),
              },
              {
                key: "message",
                label: "Detail",
                render: (r) => (
                  <span className="text-[11px] text-slate-400">{r.message ?? "—"}</span>
                ),
              },
            ]}
            rows={stages}
            empty="No stage rows recorded yet."
          />
        </Card>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <Card
          title="Source freshness"
          subtitle="MAX(ingested_at) per fact table"
          bodyClass=""
        >
          <Table
            columns={[
              { key: "table", label: "Fact table" },
              { key: "rows", label: "Rows", align: "right", render: (r) => num(r.rows) },
              { key: "last_ingested_at", label: "Last ingest", render: (r) => dateTime(r.last_ingested_at) },
              {
                key: "age_minutes",
                label: "Age",
                align: "right",
                render: (r) =>
                  r.age_minutes == null ? (
                    "—"
                  ) : (
                    <span className={Number(r.age_minutes) > 1440 ? "text-amber-300" : ""}>
                      {Number(r.age_minutes) < 60
                        ? `${Math.round(r.age_minutes)}m`
                        : `${(r.age_minutes / 60).toFixed(1)}h`}
                    </span>
                  ),
              },
            ]}
            rows={freshness}
          />
        </Card>

        <Card
          title="Incremental watermarks"
          subtitle="Last extracted value per source cursor"
          bodyClass=""
        >
          <Table
            columns={[
              { key: "source", label: "Source" },
              { key: "last_value", label: "Watermark", render: (r) => String(r.last_value ?? "—") },
              { key: "last_run_at", label: "Updated", render: (r) => dateTime(r.last_run_at) },
            ]}
            rows={watermarks}
            empty="No watermarks yet — run an incremental load."
          />
        </Card>
      </div>

      <div className="mt-3">
        <Card
          title="Declared schedule"
          subtitle="Cron expressions exposed by the DAG registry"
          bodyClass=""
        >
          {schedule.error && (
            <p className="px-4 py-3 font-mono text-xs text-rose-300">{schedule.error}</p>
          )}
          <Table
            columns={[
              { key: "dag_id", label: "DAG" },
              {
                key: "schedule",
                label: "Cron",
                render: (r) => <code className="text-[11px] text-slate-300">{r.schedule}</code>,
              },
              {
                key: "stages",
                label: "Stages",
                render: (r) => (
                  <span className="text-[11px] text-slate-400">
                    {(r.stages ?? []).join(" → ")}
                  </span>
                ),
              },
              { key: "description", label: "Purpose" },
            ]}
            rows={schedule.data?.dags ?? []}
            empty="Schedule unavailable."
          />
        </Card>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <Card title="Runner health" className="lg:col-span-1">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Runs considered" value={num(health.runs_considered)} />
            <Stat label="Successful" value={num(health.successful_runs)} />
            <Stat label="Failed" value={num(health.failed_runs)} />
            <Stat
              label="Avg duration"
              value={duration(health.avg_duration_seconds)}
            />
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            {health.scheduler ?? "in-repo runner"}
          </p>
          <p className="mt-1 text-[11px] text-slate-500">
            last success {dateTime(health.last_successful_finished_at)}
          </p>
        </Card>

        <Card
          title="Failed tasks"
          subtitle="Most recent failures across all runs"
          className="lg:col-span-2"
          bodyClass=""
        >
          <Table
            columns={[
              { key: "run_id", label: "Run", align: "right" },
              { key: "task_name", label: "Stage" },
              {
                key: "status",
                label: "Status",
                render: (r) => <Badge value={r.status} />,
              },
              { key: "attempt", label: "Try", align: "right" },
              {
                key: "message",
                label: "Message",
                render: (r) => (
                  <span className="text-[11px] text-slate-400">{r.message ?? "—"}</span>
                ),
              },
            ]}
            rows={health.failed_tasks ?? []}
            empty="No failed tasks recorded."
          />
        </Card>
      </div>
    </div>
  );
}
