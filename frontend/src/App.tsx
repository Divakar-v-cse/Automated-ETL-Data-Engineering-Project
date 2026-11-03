import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api, docsUrl } from "./lib/api";
import { Badge } from "./components/ui";
import { num } from "./lib/format";
import ExecutiveDashboard from "./pages/ExecutiveDashboard";
import SalesAnalytics from "./pages/SalesAnalytics";
import CustomerAnalytics from "./pages/CustomerAnalytics";
import ProductAnalytics from "./pages/ProductAnalytics";
import OrderExplorer from "./pages/OrderExplorer";
import PipelineMonitoring from "./pages/PipelineMonitoring";
import RunHistory from "./pages/RunHistory";
import DataQuality from "./pages/DataQuality";
import Reports from "./pages/Reports";
import SystemMonitoring from "./pages/SystemMonitoring";

const NAV = [
  { to: "/", label: "Executive dashboard", icon: "▚", end: true },
  { to: "/sales", label: "Sales analytics", icon: "▲" },
  { to: "/customers", label: "Customer analytics", icon: "◉" },
  { to: "/products", label: "Product analytics", icon: "▤" },
  { to: "/orders", label: "Order explorer", icon: "≡" },
  { to: "/pipeline", label: "Pipeline monitoring", icon: "⇄" },
  { to: "/runs", label: "Execution history", icon: "◷" },
  { to: "/data-quality", label: "Data quality", icon: "✓" },
  { to: "/reports", label: "Reports & exports", icon: "▦" },
  { to: "/system", label: "System monitoring", icon: "⛭" },
];

function Sidebar() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        className="btn-ghost fixed bottom-4 right-4 z-40 lg:hidden"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Close" : "Menu"}
      </button>
      <aside
        className={`${
          open ? "block" : "hidden"
        } fixed inset-y-0 left-0 z-30 w-64 border-r border-ink-700/80 bg-ink-950/95 px-3 py-4 backdrop-blur lg:sticky lg:top-0 lg:block lg:h-screen lg:shrink-0`}
      >
        <div className="px-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-brand-400">
            Divakar
          </p>
          <h1 className="mt-0.5 text-base font-semibold leading-tight text-white">
            Automated ETL
          </h1>
          <p className="mt-1 text-[11px] leading-snug text-slate-500">
            Data engineering platform · v1.0.0
          </p>
        </div>
        <nav className="mt-5 space-y-0.5">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] transition ${
                  isActive
                    ? "bg-brand-600/15 text-brand-400"
                    : "text-slate-400 hover:bg-ink-850 hover:text-slate-200"
                }`
              }
            >
              <span className="w-3 text-center text-xs opacity-70">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-6 rounded-lg border border-ink-700 bg-ink-900/60 p-3">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">API</p>
          <a
            href={docsUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-1 block text-xs text-brand-400 hover:underline"
          >
            OpenAPI docs ↗
          </a>
          <p className="mt-1 font-mono text-[10px] text-slate-600">/health · /api/*</p>
        </div>
      </aside>
    </>
  );
}

function TopBar() {
  const [health, setHealth] = useState<any>(null);
  useEffect(() => {
    let live = true;
    const load = () =>
      api
        .health()
        .then((h) => live && setHealth(h))
        .catch(() => live && setHealth(null));
    load();
    const id = setInterval(load, 30000);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, []);

  const rows = health?.warehouse ?? {};
  return (
    <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-2 border-b border-ink-700/70 bg-ink-950/85 px-4 py-2.5 backdrop-blur">
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <span
          className={`h-2 w-2 rounded-full ${
            health ? "bg-emerald-400" : "bg-rose-500"
          }`}
        />
        {health ? (
          <>
            <span>warehouse connected</span>
            <span className="text-slate-600">·</span>
            <span className="font-mono text-[11px]">
              {health.database?.backend} · {num(rows.fact_orders)} orders ·{" "}
              {num(rows.fact_order_items)} lines
            </span>
          </>
        ) : (
          <span>backend unreachable</span>
        )}
      </div>
      <div className="flex items-center gap-3 text-[11px] text-slate-500">
        {health?.latest_run && (
          <span className="flex items-center gap-1.5">
            run #{health.latest_run.run_id}
            <Badge value={health.latest_run.status} />
          </span>
        )}
        <span className="font-mono">{health?.version}</span>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-5">
          <Routes>
            <Route path="/" element={<ExecutiveDashboard />} />
            <Route path="/sales" element={<SalesAnalytics />} />
            <Route path="/customers" element={<CustomerAnalytics />} />
            <Route path="/products" element={<ProductAnalytics />} />
            <Route path="/orders" element={<OrderExplorer />} />
            <Route path="/pipeline" element={<PipelineMonitoring />} />
            <Route path="/runs" element={<RunHistory />} />
            <Route path="/data-quality" element={<DataQuality />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/system" element={<SystemMonitoring />} />
            <Route
              path="*"
              element={
                <p className="py-16 text-center text-sm text-slate-500">
                  Page not found.
                </p>
              }
            />
          </Routes>
        </main>
        <footer className="border-t border-ink-700/60 px-4 py-3 text-[11px] text-slate-600">
          Divakar Automated ETL Data Engineering Project · values rendered from live SQL
          against the warehouse · <span className="font-mono">GET /health</span> for
          connectivity
        </footer>
      </div>
    </div>
  );
}
