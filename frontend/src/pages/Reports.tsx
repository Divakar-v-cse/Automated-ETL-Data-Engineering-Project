import { useState } from "react";
import { api, reportDownloadUrl, reportHtmlUrl } from "../lib/api";
import { useApi } from "../lib/useApi";
import { dateTime, money, num, pct } from "../lib/format";
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

const SUMMARY_ROWS: { key: string; label: string; kind: "money" | "num" | "pct" }[] = [
  { key: "orders", label: "Orders", kind: "num" },
  { key: "revenue", label: "Revenue", kind: "money" },
  { key: "aov", label: "Average order value", kind: "money" },
  { key: "units", label: "Units sold", kind: "num" },
  { key: "discounts", label: "Discounts given", kind: "money" },
  { key: "active_customers", label: "Active customers", kind: "num" },
  { key: "new_customers", label: "New customers", kind: "num" },
  { key: "returning_customers", label: "Returning customers", kind: "num" },
  { key: "payments_attempted", label: "Payments attempted", kind: "num" },
  { key: "payment_success_rate_pct", label: "Payment success", kind: "pct" },
  { key: "settled_amount", label: "Settled amount", kind: "money" },
  { key: "returns", label: "Returns", kind: "num" },
  { key: "refund_amount", label: "Refunded", kind: "money" },
  { key: "return_rate_pct", label: "Return rate", kind: "pct" },
];

const show = (v: unknown, kind: "money" | "num" | "pct") =>
  kind === "money" ? money(v, 2) : kind === "pct" ? pct(v, 2) : num(v);

export default function Reports() {
  const [page, setPage] = useState(1);
  const [type, setType] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  const list = useApi(() => api.reports(page, 10, type), [page, type]);
  const detail = useApi(
    () => (selected ? api.report(Number(selected)) : Promise.resolve(null)),
    [selected],
  );

  const items: any[] = list.data?.items ?? [];
  const active = items.find((i) => String(i.id) === selected);
  const summary = detail.data?.summary ?? active?.summary ?? {};

  return (
    <div>
      <PageHeader
        title="Reports"
        subtitle="Daily and weekly business reports rendered from warehouse facts and stored as HTML artefacts."
        source="GET /api/reports … /{report_id} … /download"
        actions={
          <>
            <select
              className="input text-xs"
              value={type}
              onChange={(e) => {
                setType(e.target.value);
                setPage(1);
              }}
            >
              <option value="">all types</option>
              <option value="daily">daily</option>
              <option value="weekly">weekly</option>
            </select>
            <button className="btn-ghost" onClick={list.reload}>
              Refresh
            </button>
          </>
        }
      />

      {list.loading && !list.data && <Loading label="Listing generated reports…" />}
      {list.error && !list.data && <ErrorState message={list.error} onRetry={list.reload} />}

      {list.data && (
        <Card bodyClass="">
          <Table
            columns={[
              { key: "report_id", label: "Report", render: (r) => (
                <div>
                  <p className="text-xs font-medium text-slate-100">{r.title}</p>
                  <code className="text-[10px] text-slate-500">{r.report_id}</code>
                </div>
              ) },
              { key: "report_type", label: "Type", render: (r) => <Badge value={r.report_type} /> },
              {
                key: "period",
                label: "Period",
                render: (r) => (
                  <span className="text-[11px] text-slate-400">
                    {r.period_start === r.period_end
                      ? r.period_start
                      : `${r.period_start} → ${r.period_end}`}
                  </span>
                ),
              },
              {
                key: "revenue",
                label: "Revenue",
                align: "right",
                render: (r) => money(r.summary?.revenue, 2),
              },
              {
                key: "orders",
                label: "Orders",
                align: "right",
                render: (r) => num(r.summary?.orders),
              },
              {
                key: "generated_at",
                label: "Generated",
                render: (r) => <span className="text-[11px]">{dateTime(r.generated_at)}</span>,
              },
              {
                key: "actions",
                label: "",
                render: (r) => (
                  <div className="flex gap-1">
                    <button
                      className="btn-ghost px-2 py-1 text-[11px]"
                      onClick={() => setSelected(String(r.id))}
                    >
                      View
                    </button>
                    <a
                      className="btn-ghost px-2 py-1 text-[11px]"
                      href={reportHtmlUrl(r.id)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      HTML
                    </a>
                    <a
                      className="btn-ghost px-2 py-1 text-[11px]"
                      href={reportDownloadUrl(r.id)}
                    >
                      Download
                    </a>
                  </div>
                ),
              },
            ]}
            rows={items}
            empty="No reports generated for this filter."
          />
          {list.data.total > 0 && (
            <Pagination
              page={list.data.page}
              pages={list.data.pages}
              total={list.data.total}
              onPage={setPage}
            />
          )}
        </Card>
      )}

      {selected && (
        <div className="mt-3">
          <Card
            title={active?.title ?? "Report detail"}
            subtitle={`${active?.report_type ?? ""} · ${active?.period_start ?? ""} → ${active?.period_end ?? ""}`}
            actions={
              <button className="btn-ghost text-xs" onClick={() => setSelected(null)}>
                Close
              </button>
            }
          >
            {detail.loading && <Loading label="Loading report…" />}
            {detail.error && (
              <p className="font-mono text-xs text-rose-300">{detail.error}</p>
            )}
            {detail.data && (
              <>
                <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                  {SUMMARY_ROWS.filter((r) => summary[r.key] !== undefined).map((r) => (
                    <Kpi
                      key={r.key}
                      label={r.label}
                      value={show(summary[r.key], r.kind)}
                    />
                  ))}
                </div>
                {detail.data.content ? (
                  <pre className="mt-3 max-h-80 overflow-auto rounded-lg border border-ink-700 bg-ink-950/60 p-3 text-[11px] leading-relaxed text-slate-300">
                    {String(detail.data.content).slice(0, 20000)}
                  </pre>
                ) : (
                  <Empty label="This artefact is HTML — use the HTML or Download action above." />
                )}
              </>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
