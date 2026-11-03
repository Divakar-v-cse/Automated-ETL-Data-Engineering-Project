import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import { dateTime, money, num, titleCase } from "../lib/format";
import {
  Badge,
  Card,
  Empty,
  ErrorState,
  Kpi,
  Loading,
  PageHeader,
  Pagination,
  Table,
} from "../components/ui";

export default function OrderExplorer() {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [status, setStatus] = useState("");
  const [channel, setChannel] = useState("");
  const [region, setRegion] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [minTotal, setMinTotal] = useState("");
  const [sortBy, setSortBy] = useState("order_ts");
  const [openOrder, setOpenOrder] = useState<string | null>(null);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(q.trim()), 350);
    return () => clearTimeout(id);
  }, [q]);

  const { data, error, loading, reload } = useApi(
    () =>
      api.orders({
        page,
        page_size: 25,
        q: debounced,
        status,
        channel,
        region,
        date_from: dateFrom,
        date_to: dateTo,
        min_total: minTotal,
        sort_by: sortBy,
        sort_order: "desc",
      }),
    [page, debounced, status, channel, region, dateFrom, dateTo, minTotal, sortBy],
  );

  if (loading && !data) return <Loading label="Scanning fact_orders…" />;
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;

  const s = data?.summary ?? {};
  const reset = () => {
    setQ("");
    setStatus("");
    setChannel("");
    setRegion("");
    setDateFrom("");
    setDateTo("");
    setMinTotal("");
    setPage(1);
  };

  return (
    <div>
      <PageHeader
        title="Order explorer"
        subtitle="Filter the full order fact table by status, channel, region, customer, date and value."
        source="GET /api/analytics/orders"
        actions={
          <>
            <input
              className="input w-52 py-1.5 text-xs"
              placeholder="Order ID / customer"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(1);
              }}
            />
            <button className="btn-ghost text-xs" onClick={reset}>
              Reset
            </button>
            <button className="btn-ghost text-xs" onClick={reload}>
              Refresh
            </button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="Matching orders" value={num(s.orders)} hint={`${num(data?.total)} rows total`} />
        <Kpi label="Revenue in filter" value={money(s.revenue)} hint="sum(total_amount)" />
        <Kpi label="Average order value" value={money(s.avg_order_value, 2)} hint="revenue / orders" />
        <Kpi label="Units" value={num(s.units)} hint="item quantity" />
        <Kpi label="Discount" value={money(s.discount)} hint="sum(discount_amount)" />
      </div>

      <Card className="mt-3" title="Filters" bodyClass="card-pad">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
          <label className="block">
            <span className="label">Status</span>
            <input
              className="input mt-1 w-full py-1.5 text-xs"
              placeholder="delivered"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            />
          </label>
          <label className="block">
            <span className="label">Channel</span>
            <input
              className="input mt-1 w-full py-1.5 text-xs"
              placeholder="web"
              value={channel}
              onChange={(e) => {
                setChannel(e.target.value);
                setPage(1);
              }}
            />
          </label>
          <label className="block">
            <span className="label">Region</span>
            <input
              className="input mt-1 w-full py-1.5 text-xs"
              placeholder="North America"
              value={region}
              onChange={(e) => {
                setRegion(e.target.value);
                setPage(1);
              }}
            />
          </label>
          <label className="block">
            <span className="label">From</span>
            <input
              type="date"
              className="input mt-1 w-full py-1.5 text-xs"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value);
                setPage(1);
              }}
            />
          </label>
          <label className="block">
            <span className="label">To</span>
            <input
              type="date"
              className="input mt-1 w-full py-1.5 text-xs"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value);
                setPage(1);
              }}
            />
          </label>
          <label className="block">
            <span className="label">Min total</span>
            <input
              type="number"
              className="input mt-1 w-full py-1.5 text-xs"
              placeholder="0"
              value={minTotal}
              onChange={(e) => {
                setMinTotal(e.target.value);
                setPage(1);
              }}
            />
          </label>
        </div>
      </Card>

      <Card className="mt-3" title="Orders" bodyClass="">
        <Table
          columns={[
            { key: "order_id", label: "Order" },
            { key: "order_date", label: "Date" },
            { key: "customer_name", label: "Customer" },
            { key: "region", label: "Region" },
            { key: "channel", label: "Channel" },
            { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
            { key: "item_count", label: "Lines", align: "right", render: (r) => num(r.item_count) },
            {
              key: "discount_amount",
              label: "Discount",
              align: "right",
              render: (r) => money(r.discount_amount, 2),
            },
            {
              key: "total_amount",
              label: "Total",
              align: "right",
              render: (r) => money(r.total_amount, 2),
            },
            {
              key: "updated_at",
              label: "Updated",
              render: (r) => dateTime(r.updated_at),
            },
            {
              key: "open",
              label: "",
              render: (r) => (
                <button
                  className="text-xs text-brand-400 hover:underline"
                  onClick={() =>
                    setOpenOrder((cur) => (cur === r.order_id ? null : r.order_id))
                  }
                >
                  {openOrder === r.order_id ? "hide" : "detail"}
                </button>
              ),
            },
          ]}
          rows={data?.items ?? []}
        />
        <Pagination
          page={data?.page ?? 1}
          pages={data?.pages ?? 1}
          total={data?.total ?? 0}
          onPage={setPage}
        />
      </Card>

      {openOrder && <OrderDetail orderId={openOrder} />}

      <p className="mt-3 text-[11px] text-slate-600">
        Filters are pushed into SQL; the fact table is scanned once for the page, once for
        the count and once for the summary. Dimension columns for the visible page are
        resolved with a single batched lookup on{" "}
        <span className="font-mono">dim_customer</span>.
      </p>
    </div>
  );
}

function OrderDetail({ orderId }: { orderId: string }) {
  const { data, error, loading } = useApi(() => api.orderDetail(orderId), [orderId]);
  if (loading) return <Loading label={`Loading ${orderId}…`} />;
  if (error) return <ErrorState message={error} />;
  if (!data) return <Empty />;

  const o = data.order ?? data;
  return (
    <Card
      className="mt-3"
      title={`Order ${orderId}`}
      subtitle="Header, lines, payments, shipment and returns from the star schema"
    >
      <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {Object.entries({
          Status: titleCase(o.status),
          Channel: titleCase(o.channel),
          Customer: o.customer_name ?? o.customer_id,
          Region: o.region,
          Total: money(o.total_amount, 2),
          Discount: money(o.discount_amount, 2),
          Shipping: money(o.shipping_cost, 2),
          Placed: dateTime(o.order_ts),
        }).map(([k, v]) => (
          <div key={k} className="rounded-lg border border-ink-700 bg-ink-850/60 px-3 py-2">
            <p className="label">{k}</p>
            <p className="mt-0.5 text-slate-200">{String(v ?? "—")}</p>
          </div>
        ))}
      </div>

      <h3 className="mt-4 text-xs font-semibold uppercase tracking-wider text-slate-500">
        Line items
      </h3>
      <Table
        columns={[
          { key: "product_name", label: "Product" },
          { key: "sku", label: "SKU" },
          { key: "quantity", label: "Qty", align: "right", render: (r) => num(r.quantity) },
          { key: "unit_price", label: "Unit", align: "right", render: (r) => money(r.unit_price, 2) },
          { key: "discount_amount", label: "Disc.", align: "right", render: (r) => money(r.discount_amount, 2) },
          { key: "line_total", label: "Line total", align: "right", render: (r) => money(r.line_total, 2) },
        ]}
        rows={data.items ?? []}
      />

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Payments
          </h3>
          <Table
            columns={[
              { key: "payment_method", label: "Method" },
              { key: "status", label: "Status" },
              { key: "amount", label: "Amount", align: "right", render: (r) => money(r.amount, 2) },
            ]}
            rows={data.payments ?? []}
          />
        </div>
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Shipment
          </h3>
          <Table
            columns={[
              { key: "carrier", label: "Carrier" },
              { key: "status", label: "Status" },
              { key: "delivered_date", label: "Delivered" },
            ]}
            rows={data.shipments ?? []}
          />
        </div>
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Returns
          </h3>
          <Table
            columns={[
              { key: "reason", label: "Reason" },
              { key: "status", label: "Status" },
              { key: "refund_amount", label: "Refund", align: "right", render: (r) => money(r.refund_amount, 2) },
            ]}
            rows={data.returns ?? []}
          />
        </div>
      </div>
    </Card>
  );
}
