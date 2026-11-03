import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import {
  ago,
  compact,
  dateTime,
  money,
  num,
  pct,
  shortDate,
} from "../lib/format";
import {
  Badge,
  Card,
  Empty,
  ErrorState,
  Kpi,
  Loading,
  PageHeader,
  ScoreRing,
  Table,
} from "../components/ui";
import { Donut, RevenueArea, SimpleBar } from "../components/charts";

export default function ExecutiveDashboard() {
  const { data, error, loading, reload, lastUpdated } = useApi(
    () => api.overview(90),
    [],
    30000,
  );

  if (loading && !data) return <Loading label="Querying warehouse KPIs…" />;
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;

  const k = data?.kpis ?? {};
  const growth = Number(k.revenue_growth_pct ?? 0);

  return (
    <div>
      <PageHeader
        title="Executive Dashboard"
        subtitle="Revenue, order and customer performance aggregated from the warehouse at request time."
        source="GET /api/dashboard/overview"
        actions={
          <>
            <span className="text-[11px] text-slate-500">
              refreshed {lastUpdated ? ago(lastUpdated.toISOString()) : "—"}
            </span>
            <button className="btn-ghost" onClick={reload}>
              Refresh
            </button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi
          label="Total revenue"
          value={money(k.total_revenue)}
          hint={`${num(k.total_orders)} orders · AOV ${money(k.avg_order_value, 2)}`}
          tone="good"
        />
        <Kpi
          label="Revenue growth (30d vs prior)"
          value={`${growth > 0 ? "+" : ""}${growth.toFixed(1)}%`}
          hint={`${money(k.revenue_last_30d)} vs ${money(k.revenue_prev_30d)}`}
          tone={growth >= 0 ? "good" : "bad"}
        />
        <Kpi
          label="Customers"
          value={num(k.total_customers)}
          hint={`${num(k.active_customers_30d)} active in last 30 days · ${pct(
            Number(k.repeat_purchase_rate ?? 0) * 100,
          )} repeat`}
        />
        <Kpi
          label="Return rate"
          value={pct(k.return_rate)}
          hint={`${num(k.returned_orders)} returned orders · ${money(k.total_refunds)} refunded`}
          tone={Number(k.return_rate) <= 10 ? "good" : "warn"}
        />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi
          label="Payment success rate"
          value={pct(k.payment_success_rate)}
          hint={`${num(k.payment_attempts)} attempts · ${money(k.settled_amount)} settled`}
          tone={Number(k.payment_success_rate) >= 90 ? "good" : "warn"}
        />
        <Kpi
          label="Units sold"
          value={num(k.total_units)}
          hint="fact_order_items quantity"
        />
        <Kpi
          label="Discount given"
          value={money(k.total_discount)}
          hint={`${pct(
            (Number(k.total_discount) / Math.max(Number(k.total_revenue), 1)) * 100,
          )} of gross revenue`}
        />
        <Kpi
          label="Pipeline success rate"
          value={k.pipeline_success_rate === null ? "—" : pct(k.pipeline_success_rate)}
          hint={`last success ${k.last_successful_run ? dateTime(k.last_successful_run) : "—"}`}
        />
      </div>

      <div className="mt-4 grid gap-3 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="Revenue trend"
          subtitle={`Last 90 days of realised order revenue · reporting through ${shortDate(
            k.reporting_through,
          )}`}
        >
          {data?.revenue_trend?.length ? (
            <RevenueArea data={data.revenue_trend} height={280} />
          ) : (
            <Empty />
          )}
        </Card>

        <Card title="Data quality" subtitle="Composite score of the latest execution">
          <div className="flex items-center gap-4">
            <ScoreRing score={data?.quality?.score} />
            <div className="space-y-1 text-sm">
              <p className="text-slate-300">
                {num(data?.quality?.checks_passed)} / {num(data?.quality?.checks_total)} checks
                passed
              </p>
              <p className="text-slate-500">
                {num(data?.quality?.checks_failed)} failed checks
              </p>
              <Link
                to="/data-quality"
                className="inline-block text-xs text-brand-400 hover:underline"
              >
                Open data quality →
              </Link>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg bg-ink-850/70 px-3 py-2">
              <p className="label">Freshness</p>
              <p className="mt-0.5 text-slate-200">
                {data?.pipeline?.freshness_minutes === null ||
                data?.pipeline?.freshness_minutes === undefined
                  ? "—"
                  : `${num(data.pipeline.freshness_minutes)} min`}
              </p>
            </div>
            <div className="rounded-lg bg-ink-850/70 px-3 py-2">
              <p className="label">Pipeline state</p>
              <p className="mt-1">
                <Badge value={data?.pipeline?.status ?? "unknown"} />
              </p>
            </div>
          </div>
        </Card>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-3">
        <Card title="Monthly revenue" subtitle="Last 18 periods">
          {data?.monthly_revenue?.length ? (
            <SimpleBar
              data={data.monthly_revenue}
              xKey="period"
              yKey="revenue"
              height={240}
            />
          ) : (
            <Empty />
          )}
        </Card>
        <Card title="Revenue by category" subtitle="Share of settled revenue">
          {data?.top_categories?.length ? (
            <Donut
              data={data.top_categories}
              nameKey="category"
              valueKey="revenue"
              height={240}
            />
          ) : (
            <Empty />
          )}
        </Card>
        <Card title="Channel mix" subtitle="Orders by acquisition channel">
          {data?.channel_mix?.length ? (
            <Donut
              data={data.channel_mix}
              nameKey="channel"
              valueKey="revenue"
              height={240}
            />
          ) : (
            <Empty />
          )}
        </Card>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <Card
          title="Category performance"
          subtitle="Revenue, share and return rate"
          bodyClass=""
        >
          <Table
            columns={[
              { key: "category", label: "Category" },
              { key: "orders", label: "Orders", align: "right", render: (r) => num(r.orders) },
              { key: "units", label: "Units", align: "right", render: (r) => num(r.units) },
              { key: "revenue", label: "Revenue", align: "right", render: (r) => money(r.revenue) },
              {
                key: "revenue_share_pct",
                label: "Share",
                align: "right",
                render: (r) => pct(r.revenue_share_pct),
              },
              {
                key: "return_rate_pct",
                label: "Return %",
                align: "right",
                render: (r) => pct(r.return_rate_pct, 2),
              },
            ]}
            rows={data?.top_categories ?? []}
          />
        </Card>

        <Card title="Recent pipeline runs" subtitle="From the orchestration ledger" bodyClass="">
          <Table
            columns={[
              { key: "run_id", label: "Run" },
              { key: "dag_id", label: "Workflow" },
              { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
              {
                key: "records_loaded",
                label: "Loaded",
                align: "right",
                render: (r) => num(r.records_loaded),
              },
              {
                key: "records_rejected",
                label: "Rejected",
                align: "right",
                render: (r) => num(r.records_rejected),
              },
              { key: "started_at", label: "Started", render: (r) => dateTime(r.started_at) },
            ]}
            rows={data?.recent_runs ?? []}
          />
        </Card>
      </div>

      <p className="mt-4 text-[11px] text-slate-600">
        All values are computed by SQL against the warehouse on each request — no metric is
        hardcoded in the UI. Forecasts, where present, are labelled and never mixed with actuals.
      </p>
    </div>
  );
}
