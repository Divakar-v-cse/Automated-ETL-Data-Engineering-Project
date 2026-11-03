import { useState } from "react";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import { dateTime, duration, num, pct } from "../lib/format";
import {
  Badge,
  Card,
  ErrorState,
  Loading,
  PageHeader,
  Pagination,
  Table,
} from "../components/ui";

export default function RunHistory() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [dagId, setDagId] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const history = useApi(
    () => api.pipelineHistory(page, 10, status, dagId),
    [page, status, dagId],
  );
  const detail = useApi(
    () => (expanded ? api.pipelineHistory(1, 1, "", "", expanded) : Promise.resolve(null)),
    [expanded],
  );

  const items: any[] = history.data?.items ?? [];

  return (
    <div>
      <PageHeader
        title="Run History"
        subtitle="Every execution written to the pipeline ledger, with per-stage attempts and messages."
        source="GET /api/pipeline/history"
        actions={
          <>
            <select
              className="input text-xs"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            >
              <option value="">all statuses</option>
              <option value="success">success</option>
              <option value="failed">failed</option>
              <option value="running">running</option>
            </select>
            <select
              className="input text-xs"
              value={dagId}
              onChange={(e) => {
                setDagId(e.target.value);
                setPage(1);
              }}
            >
              <option value="">all DAGs</option>
              <option value="daily_etl_pipeline">daily_etl_pipeline</option>
              <option value="incremental_ingestion_pipeline">incremental_ingestion_pipeline</option>
              <option value="data_quality_pipeline">data_quality_pipeline</option>
              <option value="analytics_pipeline">analytics_pipeline</option>
              <option value="reporting_pipeline">reporting_pipeline</option>
            </select>
            <button className="btn-ghost" onClick={history.reload}>
              Refresh
            </button>
          </>
        }
      />

      {history.loading && !history.data && <Loading label="Reading execution history…" />}
      {history.error && !history.data && (
        <ErrorState message={history.error} onRetry={history.reload} />
      )}

      {history.data && (
        <Card bodyClass="">
          <Table
            columns={[
              { key: "run_id", label: "#", align: "right", render: (r) => `#${r.run_id}` },
              {
                key: "dag_id",
                label: "DAG",
                render: (r) => (
                  <code className="text-[11px] text-slate-300">{r.dag_id}</code>
                ),
              },
              {
                key: "status",
                label: "Status",
                render: (r) => <Badge value={r.status} />,
              },
              { key: "trigger", label: "Trigger" },
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
                key: "records",
                label: "Ext / Trf / Load / Rej",
                align: "right",
                render: (r) => (
                  <span className="font-mono text-[11px] text-slate-400">
                    {num(r.records_extracted)} / {num(r.records_transformed)} /{" "}
                    {num(r.records_loaded)} / {num(r.records_rejected)}
                  </span>
                ),
              },
              {
                key: "quality_score",
                label: "Quality",
                align: "right",
                render: (r) => pct(r.quality_score),
              },
              {
                key: "detail",
                label: "",
                render: (r) => (
                  <button
                    className="btn-ghost px-2 py-1 text-[11px]"
                    onClick={() => setExpanded(expanded === r.run_id ? null : r.run_id)}
                  >
                    {expanded === r.run_id ? "Hide" : "Stages"}
                  </button>
                ),
              },
            ]}
            rows={items}
            empty="No runs match this filter."
          />
          {history.data.total > 0 && (
            <Pagination
              page={history.data.page}
              pages={history.data.pages}
              total={history.data.total}
              onPage={setPage}
            />
          )}
        </Card>
      )}

      {expanded != null && (
        <div className="mt-3">
          <Card
            title={`Stage detail — run #${expanded}`}
            subtitle="Attempts, timings and log messages recorded per task"
            bodyClass=""
          >
            {detail.loading && <Loading label="Loading stages…" />}
            {detail.error && <p className="px-4 py-3 font-mono text-xs text-rose-300">{detail.error}</p>}
            {detail.data && (
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
                    key: "finished_at",
                    label: "Finished",
                    render: (r) => <span className="text-xs">{dateTime(r.finished_at)}</span>,
                  },
                  {
                    key: "duration_seconds",
                    label: "Duration",
                    align: "right",
                    render: (r) => duration(r.duration_seconds),
                  },
                  {
                    key: "message",
                    label: "Message",
                    render: (r) => (
                      <span className="text-[11px] text-slate-400">{r.message ?? "—"}</span>
                    ),
                  },
                ]}
                rows={detail.data.tasks ?? []}
                empty="No task rows for this run."
              />
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
