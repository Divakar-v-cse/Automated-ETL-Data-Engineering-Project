import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import { money, num, pct } from "../lib/format";
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
import { SimpleBar } from "../components/charts";

const SORTS = [
  { key: "revenue", label: "Revenue" },
  { key: "units", label: "Units" },
  { key: "orders", label: "Orders" },
  { key: "return_rate_pct", label: "Return rate" },
  { key: "unit_price", label: "Unit price" },
];

export default function ProductAnalytics() {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("revenue");
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const id = setTimeout(() => setDebounced(q.trim()), 350);
    return () => clearTimeout(id);
  }, [q]);

  const { data, error, loading, reload } = useApi(
    () => api.products(page, 20, sortBy, "desc", category, debounced),
    [page, sortBy, category, debounced],
  );

  if (loading && !data) return <Loading label="Scanning product performance…" />;
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;

  const s = data?.summary ?? {};
  const table = data?.products ?? { items: [], pages: 1, page: 1, total: 0 };

  return (
    <div>
      <PageHeader
        title="Product analytics"
        subtitle="Product-level revenue, volume, discount depth and return exposure."
        source={`GET /api/analytics/products?sort_by=${sortBy}${category ? `&category=${category}` : ""}`}
        actions={
          <>
            <input
              className="input w-48 py-1.5 text-xs"
              placeholder="Search product / brand"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(1);
              }}
            />
            <select
              className="input py-1.5 text-xs"
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All categories</option>
              {(data?.by_category ?? []).map((c: any) => (
                <option key={c.category} value={c.category}>
                  {c.category}
                </option>
              ))}
            </select>
            <select
              className="input py-1.5 text-xs"
              value={sortBy}
              onChange={(e) => {
                setSortBy(e.target.value);
                setPage(1);
              }}
            >
              {SORTS.map((o) => (
                <option key={o.key} value={o.key}>
                  Sort: {o.label}
                </option>
              ))}
            </select>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="Products" value={num(s.products)} hint={`${num(s.categories)} categories`} />
        <Kpi label="Revenue" value={money(s.revenue)} hint="all product lines" tone="good" />
        <Kpi label="Units sold" value={num(s.units)} hint="quantity shipped" />
        <Kpi label="Returned units" value={num(s.returned_units)} hint={`${money(s.refunds)} refunded`} />
        <Kpi
          label="Return rate"
          value={pct(s.return_rate_pct, 2)}
          hint="returned / units"
          tone={Number(s.return_rate_pct) <= 10 ? "good" : "warn"}
        />
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <Card title="Revenue by category" subtitle="Share of total product revenue">
          {data?.by_category?.length ? (
            <SimpleBar
              data={data.by_category}
              xKey="category"
              yKey="revenue"
              horizontal
              height={280}
            />
          ) : (
            <Empty />
          )}
        </Card>
        <Card title="Category detail" bodyClass="">
          <Table
            columns={[
              { key: "category", label: "Category" },
              { key: "products", label: "SKUs", align: "right", render: (r) => num(r.products) },
              { key: "units", label: "Units", align: "right", render: (r) => num(r.units) },
              { key: "revenue", label: "Revenue", align: "right", render: (r) => money(r.revenue) },
              { key: "avg_discount_pct", label: "Disc.", align: "right", render: (r) => pct(r.avg_discount_pct, 1) },
              { key: "return_rate_pct", label: "Return", align: "right", render: (r) => pct(r.return_rate_pct, 2) },
            ]}
            rows={data?.by_category ?? []}
          />
        </Card>
      </div>

      <Card
        className="mt-3"
        title="Product catalogue"
        subtitle={`${num(table.total)} products match the current filters`}
        bodyClass=""
      >
        <Table
          columns={[
            { key: "revenue_rank", label: "#", render: (r) => r.revenue_rank ?? "—" },
            { key: "product_name", label: "Product" },
            { key: "category", label: "Category" },
            { key: "brand", label: "Brand" },
            { key: "unit_price", label: "Price", align: "right", render: (r) => money(r.unit_price, 2) },
            { key: "units", label: "Units", align: "right", render: (r) => num(r.units) },
            { key: "revenue", label: "Revenue", align: "right", render: (r) => money(r.revenue) },
            { key: "avg_discount_pct", label: "Disc.", align: "right", render: (r) => pct(r.avg_discount_pct, 1) },
            { key: "return_rate_pct", label: "Return", align: "right", render: (r) => pct(r.return_rate_pct, 2) },
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

      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <Card title="Best sellers" subtitle="By units" bodyClass="">
          <Table
            columns={[
              { key: "product_name", label: "Product" },
              { key: "units", label: "Units", align: "right", render: (r) => num(r.units) },
              { key: "revenue", label: "Revenue", align: "right", render: (r) => money(r.revenue) },
            ]}
            rows={data?.best_sellers ?? []}
          />
        </Card>
        <Card
          title="Highest return rates"
          subtitle="Minimum 20 units to qualify"
          bodyClass=""
        >
          <Table
            columns={[
              { key: "product_name", label: "Product" },
              { key: "returned_units", label: "Returned", align: "right", render: (r) => num(r.returned_units) },
              { key: "return_rate_pct", label: "Rate", align: "right", render: (r) => pct(r.return_rate_pct, 2) },
              { key: "revenue", label: "Revenue", align: "right", render: (r) => money(r.revenue) },
            ]}
            rows={data?.worst_return_rates ?? []}
          />
        </Card>
      </div>
    </div>
  );
}
