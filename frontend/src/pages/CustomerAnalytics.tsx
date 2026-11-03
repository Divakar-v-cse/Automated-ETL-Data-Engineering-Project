import { useState } from "react";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import { dateTime, money, num, pct } from "../lib/format";
import {
  Card,
  Empty,
  ErrorState,
  Kpi,
  Loading,
  PageHeader,
  Pagination,
  Table,
} from "../components/ui";
import { DualBarLine, SimpleBar } from "../components/charts";

const SORTS = [
  { key: "predicted_clv", label: "Predicted CLV" },
  { key: "historical_revenue", label: "Historical revenue" },
  { key: "orders", label: "Orders" },
  { key: "avg_order_value", label: "Average order value" },
];

export default function CustomerAnalytics() {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("predicted_clv");
  const { data, error, loading, reload } = useApi(
    () => api.customers(page, 25, sortBy),
    [page, sortBy],
  );

  if (loading && !data) return <Loading label="Scoring customer cohorts…" />;
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;

  const s = data?.summary ?? {};
  const table = data?.top_customers ?? { items: [], pages: 1, page: 1, total: 0 };

  return (
    <div>
      <PageHeader
        title="Customer analytics"
        subtitle="New vs returning mix, RFM segmentation, retention cohorts and customer lifetime value."
        source={`GET /api/analytics/customers?page=${page}&sort_by=${sortBy}`}
        actions={
          <button className="btn-ghost" onClick={reload}>
            Refresh
          </button>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="Total customers" value={num(s.total_customers)} hint="dim_customer current rows" />
        <Kpi label="Purchasing customers" value={num(s.purchasing_customers)} hint="at least one order" />
        <Kpi
          label="Repeat purchase rate"
          value={pct(Number(s.repeat_purchase_rate ?? 0))}
          hint={`${num(s.repeat_customers)} repeat customers`}
          tone="good"
        />
        <Kpi label="New in last 30d" value={num(s.new_customers_30d)} hint="first order within window" />
        <Kpi
          label="At-risk customers"
          value={num(s.at_risk_customers)}
          hint="RFM segment At Risk"
          tone={Number(s.at_risk_customers) > 0 ? "warn" : "neutral"}
        />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Avg predicted CLV" value={money(s.avg_predicted_clv, 2)} hint="model estimate" />
        <Kpi label="Total predicted CLV" value={money(s.total_predicted_clv)} hint="sum of estimates" />
        <Kpi label="Realised revenue" value={money(s.historical_revenue)} hint="actual order revenue" />
        <Kpi label="Orders / customer" value={num(s.avg_orders_per_customer, 2)} hint="lifetime average" />
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="New vs returning customers"
          subtitle="Monthly active customers split by first-purchase month"
        >
          {data?.new_vs_returning?.length ? (
            <DualBarLine
              data={data.new_vs_returning}
              xKey="period"
              barKey="new_customers"
              lineKey="active_customers"
              height={280}
            />
          ) : (
            <Empty />
          )}
        </Card>
        <Card title="RFM segments" subtitle="Customers per segment">
          {data?.rfm_segments?.length ? (
            <SimpleBar
              data={data.rfm_segments.slice(0, 8)}
              xKey="rfm_segment"
              yKey="customers"
              horizontal
              height={280}
              color="#34d399"
              valueFormatter={(v) => num(v)}
            />
          ) : (
            <Empty />
          )}
        </Card>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <Card title="Retention by cohort" subtitle="month_index ≤ 12" bodyClass="">
          <Table
            columns={[
              { key: "cohort_month", label: "Cohort" },
              { key: "month_index", label: "M+", align: "right" },
              { key: "cohort_size", label: "Cohort", align: "right", render: (r) => num(r.cohort_size) },
              {
                key: "active_customers",
                label: "Active",
                align: "right",
                render: (r) => num(r.active_customers),
              },
              {
                key: "retention_rate_pct",
                label: "Retention",
                align: "right",
                render: (r) => pct(r.retention_rate_pct),
              },
            ]}
            rows={(data?.retention ?? []).slice(0, 30)}
          />
        </Card>
        <Card title="CLV distribution" subtitle="Customers and revenue by CLV band" bodyClass="">
          <Table
            columns={[
              { key: "clv_band", label: "Band" },
              { key: "customers", label: "Customers", align: "right", render: (r) => num(r.customers) },
              {
                key: "avg_predicted_clv",
                label: "Avg CLV",
                align: "right",
                render: (r) => money(r.avg_predicted_clv, 2),
              },
              {
                key: "historical_revenue",
                label: "Realised",
                align: "right",
                render: (r) => money(r.historical_revenue),
              },
            ]}
            rows={data?.clv_distribution ?? []}
          />
        </Card>
      </div>

      <Card
        className="mt-3"
        title="Customer leaderboard"
        subtitle="Sorted by the selected CLV metric"
        bodyClass=""
        actions={
          <select
            className="input py-1 text-xs"
            value={sortBy}
            onChange={(e) => {
              setSortBy(e.target.value);
              setPage(1);
            }}
          >
            {SORTS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        }
      >
        <Table
          columns={[
            { key: "customer_id", label: "Customer" },
            { key: "full_name", label: "Name" },
            { key: "segment", label: "Segment" },
            { key: "region", label: "Region" },
            { key: "orders", label: "Orders", align: "right", render: (r) => num(r.orders) },
            {
              key: "historical_revenue",
              label: "Revenue",
              align: "right",
              render: (r) => money(r.historical_revenue),
            },
            {
              key: "predicted_clv",
              label: "Predicted CLV",
              align: "right",
              render: (r) => money(r.predicted_clv, 2),
            },
            { key: "clv_band", label: "Band" },
            {
              key: "last_order_date",
              label: "Last order",
              render: (r) => dateTime(r.last_order_date),
            },
          ]}
          rows={table.items ?? []}
        />
        <Pagination
          page={table.page ?? 1}
          pages={table.pages ?? 1}
          total={table.total ?? 0}
          onPage={setPage}
        />
      </Card>

      <p className="mt-3 text-[11px] text-slate-600">{s.clv_note}</p>
    </div>
  );
}
