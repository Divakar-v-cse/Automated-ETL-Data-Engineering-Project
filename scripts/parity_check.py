"""Independent SQL parity check: recompute KPI values straight from the warehouse."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "db" / "warehouse.db"
con = sqlite3.connect(DB)
cur = con.cursor()


def q(sql: str):
    return cur.execute(sql).fetchone()


print("DB file:", DB, "size_mb:", round(DB.stat().st_size / 1e6, 1))

print("\n--- fact_orders by status ---")
for status, n, total in cur.execute(
        "SELECT status, COUNT(*), ROUND(SUM(total_amount),2) FROM fact_orders "
        "GROUP BY status ORDER BY 2 DESC"):
    print(f"  {status:<12} rows={n:>6}  sum_total={total:>14,.2f}")

print("\n--- candidate totals ---")
for label, sql in [
    ("all orders", "SELECT COUNT(*), ROUND(SUM(total_amount),2) FROM fact_orders"),
    ("excluding cancelled",
     "SELECT COUNT(*), ROUND(SUM(total_amount),2) FROM fact_orders WHERE status <> 'cancelled'"),
    ("excluding cancelled+returned",
     "SELECT COUNT(*), ROUND(SUM(total_amount),2) FROM fact_orders "
     "WHERE status NOT IN ('cancelled','returned')"),
]:
    n, total = q(sql)
    print(f"  {label:<28} orders={n:>6}  revenue={total:>14,.2f}")

print("\n--- dimensions / units ---")
print("  current customers :", q("SELECT COUNT(DISTINCT customer_id) FROM dim_customer WHERE is_current=1")[0])
print("  all customer rows :", q("SELECT COUNT(*) FROM dim_customer")[0])
print("  distinct versions :", q("SELECT COUNT(DISTINCT version) FROM dim_customer")[0])
print("  units sold        :", q("SELECT SUM(quantity) FROM fact_order_items")[0])
print("  products current  :", q("SELECT COUNT(*) FROM dim_product WHERE is_current=1")[0])

print("\n--- latest run ---")
for row in cur.execute("SELECT run_id, dag_id, status, records_loaded, records_rejected, "
                       "quality_score, duration_seconds FROM pipeline_runs "
                       "ORDER BY run_id DESC LIMIT 3"):
    print("  ", row)

print("\n--- quarantine ---")
print("  total rows:", q("SELECT COUNT(*) FROM quarantine")[0])
for reason, n in cur.execute("SELECT reason, COUNT(*) FROM quarantine GROUP BY reason "
                             "ORDER BY 2 DESC LIMIT 6"):
    print(f"   {reason:<32} {n}")

print("\n--- API values for comparison ---")
payload = json.load(__import__("urllib.request", fromlist=["request"]).urlopen(
    "http://127.0.0.1:8010/api/dashboard/overview?days=90", timeout=120))
k = payload["kpis"]
for key in ("total_revenue", "total_orders", "total_customers", "total_units", "avg_order_value"):
    print(f"  {key:<18} {k.get(key)}")
print("  quality           ", payload.get("quality"))
print("  pipeline          ", {kk: payload.get("pipeline", {}).get(kk)
                               for kk in ("status", "freshness_minutes", "last_run_id")})
con.close()
