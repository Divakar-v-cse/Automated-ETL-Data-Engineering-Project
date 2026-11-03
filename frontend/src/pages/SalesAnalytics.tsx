import { useState } from "react";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import { compact, money, num, pct, shortDate } from "../lib/format";
import {
  Card,
  Empty,
  ErrorState,
  Kpi,
  Loading,
  PageHeader,
  Table,
} from "../components/ui";
import { Donut, ForecastChart, RevenueArea, SimpleBar } from "../components/charts";

export default function SalesAnalytics() {
  const [days, setDays] = useState(180);
  const { data, error, loading, reload } = useApi(() => api.sales(days), [days]);

  if (loading && !data) return <Loading label="Aggregating sales facts…" />;
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;
  const s = data?.summary ?? {};

  return (
    <div>
      <PageHeader
        title="Sales analytics"
        subtitle="Revenue, discount, region, channel and payment-method performance with a labelled 30-day forecast."
        source={`GET /api/analytics/sales?days=${days}`}
        actions={
          <select
            className="input text-xs"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            {[30, 90, 180, 365].map((d) => (
              <option key={d} value={d}>
                Last {d} days
              </option>
            ))}
          </select>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="Revenue" value={money(s.revenue)} hint={`${num(s.orders)} orders`} tone="good" />
        <Kpi label="Average order value" value={money(s.avg_order_value, 2)} hint="revenue / orders" />
        <Kpi label="Units sold" value={num(s.units)} hint="fact_order_items.quantity" />
        <Kpi label="Discount" value={money(s.discount)} hint={`${pct(s.discount_pct, 2)} of gross`} />
        <Kpi label="Revenue / day" value={money(s.revenue_per_day)} hint={`${days}-day window`} />
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="Daily revenue with moving averages"
          subtitle="7-day and 30-day trailing means from mart_sales_daily"
        >
          {data?.daily?.length ? (
            <RevenueArea data={data.daily} height={300} />
          ) : (
            <Empty />
          )}
        </Card>
        <Card title="Payment methods" subtitle="Settled amount by method and provider">
          {data?.payment_methods?.length ? (
            <Table
              columns={[
                { key: "payment_method", label: "Method" },
                { key: "attempts", label: "Att.", align: "right", render: (r) => num(r.attempts) },
                {
                  key: "success_rate_pct",
                  label: "Success",
                  align: "right",
                  render: (r) => pct(r.success_rate_pct),
                },
                {
                  key: "settled_amount",
                  label: "Settled",
                  align: "right",
                  render: (r) => money(r.settled_amount),
                },
              ]}
              rows={data.payment_methods}
            />
          ) : (
            <Empty />
          )}
        </Card>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <Card title="Monthly revenue" subtitle="Trailing 24 periods">
          {data?.monthly?.length ? (
            <SimpleBar data={data.monthly} xKey="period" yKey="revenue" height={260} />
          ) : (
            <Empty />
          )}
        </Card>
        <Card
          title="Revenue forecast"
          subtitle={
            s.forecast_model
              ? `${s.forecast_model} · ${s.forecast_days} days ahead`
              : "Model forecast"
          }
        >
          {data?.forecast?.length ? (
            <ForecastChart data={data.forecast} height={260} />
          ) : (
            <Empty />
          )}
        </Card>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-3">
        <Card title="Revenue by category">
          {data?.by_category?.length ? (
            <Donut data={data.by_category} nameKey="category" valueKey="revenue" height={240} />
          ) : (
            <Empty />
          )}
        </Card>
        <Card title="Revenue by region">
          {data?.by_region?.length ? (
            <Donut data={data.by_region} nameKey="region" valueKey="revenue" height={240} />
          ) : (
            <Empty />
          )}
        </Card>
        <Card title="Revenue by channel">
          {data?.by_channel?.length ? (
            <Donut data={data.by_channel} nameKey="channel" valueKey="revenue" height={240} />
          ) : (
            <Empty />
          )}
        </Card>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <Card title="Region performance" bodyClass="">
          <Table
            columns={[
              { key: "region", label: "Region" },
              { key: "orders", label: "Orders", align: "right", render: (r) => num(r.orders) },
              { key: "customers", label: "Customers", align: "right", render: (r) => num(r.customers) },
              { key: "avg_order_value", label: "AOV", align: "right", render: (r) => money(r.avg_order_value, 2) },
              { key: "revenue", label: "Revenue", align: "right", render: (r) => money(r.revenue) },
              { key: "revenue_share_pct", label: "Share", align: "right", render: (r) => pct(r.revenue_share_pct) },
            ]}
            rows={data?.by_region ?? []}
          />
        </Card>
        <Card title="Discount impact" subtitle="Revenue and volume by discount bucket" bodyClass="">
          <Table
            columns={[
              { key: "discount_bucket", label: "Bucket" },
              { key: "lines", label: "Lines", align: "right", render: (r) => num(r.lines) },
              { key: "units", label: "Units", align: "right", render: (r) => num(r.units) },
              { key: "avg_discount_pct", label: "Avg disc.", align: "right", render: (r) => pct(r.avg_discount_pct, 2) },
              { key: "avg_line_value", label: "Avg line", align: "right", render: (r) => money(r.avg_line_value, 2) },
              { key: "revenue", label: "Revenue", align: "right", render: (r) => money(r.revenue) },
            ]}
            rows={data?.discount_impact ?? []}
          />
        </Card>
      </div>

      <Card
        className="mt-3"
        title="Top products by revenue"
        subtitle="Joined from mart_product_performance"
        bodyClass=""
      >
        <Table
          columns={[
            { key: "revenue_rank", label: "#", render: (r) => r.revenue_rank ?? "—" },
            { key: "product_name", label: "Product" },
            { key: "category", label: "Category" },
            { key: "brand", label: "Brand" },
            { key: "units", label: "Units", align: "right", render: (r) => num(r.units) },
            { key: "revenue", label: "Revenue", align: "right", render: (r) => money(r.revenue) },
            { key: "avg_discount_pct", label: "Disc.", align: "right", render: (r) => pct(r.avg_discount_pct, 1) },
            { key: "return_rate_pct", label: "Return", align: "right", render: (r) => pct(r.return_rate_pct, 2) },
          ]}
          rows={data?.top_products ?? []}
        />
      </Card>

      <p className="mt-3 text-[11px] text-slate-600">
        Forecast rows carry <span className="font-mono">kind = forecast</span> and are drawn
        dashed; actuals are never overwritten. Forecast model:{" "}
        <span className="font-mono">{s.forecast_model ?? "n/a"}</span>. Window starts{" "}
        {shortDate(data?.daily?.[0]?.order_date)} · peak day{" "}
        {money(Math.max(...(data?.daily ?? []).map((d: any) => Number(d.revenue) || 0)), 0)} ·
        total {compact(s.revenue)}.
      </p>
    </div>
  );
}
