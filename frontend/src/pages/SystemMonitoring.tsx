import { api, docsUrl } from "../lib/api";
import { useApi } from "../lib/useApi";
import { ago, dateTime, duration, num } from "../lib/format";
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

const EXPECTED_ENDPOINTS = [
  ["GET", "/health", "Service + warehouse row counts"],
  ["GET", "/api/dashboard/overview", "Executive KPIs and trends"],
  ["GET", "/api/analytics/sales", "Revenue, category, region, channel"],
  ["GET", "/api/analytics/customers", "CLV, RFM, retention"],
  ["GET", "/api/analytics/products", "Catalogue performance"],
  ["GET", "/api/analytics/orders", "Order explorer + filters"],
  ["GET", "/api/pipeline/status", "Live runner state and freshness"],
  ["GET", "/api/pipeline/history", "Execution ledger"],
  ["GET", "/api/data-quality", "DQ score, checks, quarantine"],
  ["GET", "/api/reports", "Generated report artefacts"],
  ["POST", "/api/pipeline/trigger", "Start a DAG (202 / 409)"],
  ["POST", "/api/pipeline/backfill", "Replay a date window"],
];

export default function SystemMonitoring() {
  const health = useApi(() => api.health(), [], 20000);
  const status = useApi(() => api.pipelineStatus(), [], 20000);
  const schedule = useApi(() => api.schedule(), []);

  if (health.loading && !health.data) return <Loading label="Probing backend…" />;
  if (health.error && !health.data)
    return <ErrorState message={health.error} onRetry={health.reload} />;

  const h = health.data ?? {};
  const warehouse: Record<string, number> = h.warehouse ?? {};
  const db = h.database ?? {};
  const latest = h.latest_run ?? {};
  const freshness: any[] = status.data?.freshness ?? [];
  const marts = Object.entries(warehouse).filter(([k]) => k.startsWith("mart_") || k.startsWith("dim_") || k.startsWith("fact_"));

  return (
    <div>
      <PageHeader
        title="System Monitoring"
        subtitle="Backend process, database connectivity, warehouse inventory and the endpoint contract."
        source="GET /health · /api/pipeline/status · /api/pipeline/schedule"
        actions={
          <>
            <a className="btn-ghost" href={docsUrl} target="_blank" rel="noreferrer">
              OpenAPI docs
            </a>
            <button className="btn-ghost" onClick={health.reload}>
              Refresh
            </button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi
          label="API"
          value={<Badge value={h.status === "ok" ? "healthy" : "down"} />}
          hint={h.app ?? "—"}
          tone={h.status === "ok" ? "good" : "bad"}
        />
        <Kpi
          label="Database"
          value={<Badge value={db.database ?? "unknown"} />}
          hint={`${db.backend ?? "?"} · ${db.url_scheme ?? "?"}`}
          tone={db.database === "up" ? "good" : "bad"}
        />
        <Kpi
          label="Fact orders"
          value={num(warehouse.fact_orders)}
          hint={`${num(warehouse.fact_order_items)} order lines`}
        />
        <Kpi
          label="Dimension rows"
          value={num(
            (warehouse.dim_customer ?? 0) + (warehouse.dim_product ?? 0) + (warehouse.dim_date ?? 0),
          )}
          hint={`${num(warehouse.dim_customer)} customers · ${num(warehouse.dim_product)} products`}
        />
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <Card title="Service identity" className="lg:col-span-1">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Version" value={h.version ?? "—"} />
            <Stat label="Checked" value={ago(h.generated_at)} />
            <Stat label="Latest run" value={`#${latest.run_id ?? "—"}`} />
            <Stat label="Run status" value={<Badge value={latest.status} />} />
            <Stat label="Duration" value={duration(latest.duration_seconds)} />
            <Stat label="Quality" value={latest.quality_score ?? "—"} />
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            Served by FastAPI on port 8010; the compiled React bundle is mounted on the same
            origin so every page and API call share one host.
          </p>
        </Card>

        <Card
          title="Warehouse inventory"
          subtitle="Row counts read live from the warehouse"
          className="lg:col-span-1"
          bodyClass=""
        >
          <Table
            columns={[
              { key: "table", label: "Table" },
              { key: "rows", label: "Rows", align: "right", render: (r) => num(r.rows) },
              {
                key: "kind",
                label: "Layer",
                render: (r) => (
                  <span className="text-[11px] text-slate-400">
                    {r.table.startsWith("dim_")
                      ? "dimension"
                      : r.table.startsWith("fact_")
                        ? "fact"
                        : "mart"}
                  </span>
                ),
              },
            ]}
            rows={marts.map(([table, rows]) => ({ table, rows }))}
          />
        </Card>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <Card
          title="Fact freshness"
          subtitle="Age of the most recent ingest per fact table"
          bodyClass=""
        >
          <Table
            columns={[
              { key: "table", label: "Table" },
              { key: "rows", label: "Rows", align: "right", render: (r) => num(r.rows) },
              {
                key: "last_ingested_at",
                label: "Last ingest",
                render: (r) => <span className="text-[11px]">{dateTime(r.last_ingested_at)}</span>,
              },
              {
                key: "age_minutes",
                label: "Age",
                align: "right",
                render: (r) => (r.age_minutes == null ? "—" : ago(r.last_ingested_at)),
              },
            ]}
            rows={freshness}
            empty="Pipeline status unavailable."
          />
        </Card>

        <Card title="Scheduler" subtitle="Declared DAG cadence" bodyClass="">
          <Table
            columns={[
              { key: "dag_id", label: "DAG", render: (r) => <code className="text-[11px]">{r.dag_id}</code> },
              { key: "schedule", label: "Cron" },
              {
                key: "stage_count",
                label: "Stages",
                align: "right",
                render: (r) => num((r.stages ?? []).length),
              },
            ]}
            rows={schedule.data?.dags ?? []}
            empty="Schedule unavailable."
          />
          <p className="mt-3 px-1 text-[11px] text-slate-500">
            Retries per task: {schedule.data?.retries ?? "—"} · scheduler:{" "}
            {status.data?.health?.scheduler ?? "in-repo runner"}
          </p>
        </Card>
      </div>

      <div className="mt-3">
        <Card
          title="Endpoint contract"
          subtitle="The twelve required routes and their responsibility"
          bodyClass=""
        >
          <Table
            columns={[
              {
                key: "method",
                label: "Method",
                render: (r) => (
                  <span className={r.method === "GET" ? "text-sky-300" : "text-amber-300"}>
                    {r.method}
                  </span>
                ),
              },
              { key: "path", label: "Path", render: (r) => <code className="text-[11px]">{r.path}</code> },
              { key: "purpose", label: "Purpose" },
            ]}
            rows={EXPECTED_ENDPOINTS.map(([method, path, purpose]) => ({ method, path, purpose }))}
          />
        </Card>
      </div>
    </div>
  );
}
