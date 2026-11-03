"""Warehouse-level data-quality checks, scoring and report generation.

Every check is a single SQL statement that returns a violation count, so the
same code runs unchanged on PostgreSQL and SQLite.  Results are persisted to
``data_quality_results`` after each execution and summarised into a 0-100 score.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from sqlalchemy import text

from etl.db import get_engine


@dataclass
class Check:
    name: str
    entity: str
    sql: str
    threshold: float = 0.0
    severity: str = "error"  # error -> fail, warn -> warning
    description: str = ""


CHECKS: list[Check] = [
    Check("no_orphan_order_customers", "fact_orders",
          "SELECT COUNT(*) FROM fact_orders f "
          "LEFT JOIN dim_customer c ON f.customer_key = c.customer_key "
          "WHERE c.customer_key IS NULL", 0, "error",
          "Every order must resolve to a customer dimension row"),
    Check("no_duplicate_orders", "fact_orders",
          "SELECT COUNT(*) FROM (SELECT order_id FROM fact_orders "
          "GROUP BY order_id HAVING COUNT(*) > 1) t", 0, "error",
          "order_id must be unique in the order fact"),
    Check("order_totals_reconcile", "fact_orders",
          "SELECT COUNT(*) FROM fact_orders WHERE ABS(total_amount - "
          "(order_amount - discount_amount + shipping_cost)) > 0.02", 0, "error",
          "total_amount = order_amount - discount + shipping"),
    Check("orders_have_valid_dates", "fact_orders",
          "SELECT COUNT(*) FROM fact_orders f LEFT JOIN dim_date d "
          "ON f.date_key = d.date_key WHERE d.date_key IS NULL", 0, "error",
          "date_key must exist in dim_date"),
    Check("no_orphan_order_items", "fact_order_items",
          "SELECT COUNT(*) FROM fact_order_items i LEFT JOIN fact_orders o "
          "ON i.order_key = o.order_key WHERE o.order_key IS NULL", 0, "error",
          "Order lines must resolve to an order"),
    Check("no_orphan_item_products", "fact_order_items",
          "SELECT COUNT(*) FROM fact_order_items i LEFT JOIN dim_product p "
          "ON i.product_key = p.product_key WHERE p.product_key IS NULL", 0, "error",
          "Order lines must resolve to a product"),
    Check("no_negative_prices", "fact_order_items",
          "SELECT COUNT(*) FROM fact_order_items WHERE unit_price < 0 OR line_total < 0",
          0, "error", "Prices and line totals must be non-negative"),
    Check("payment_amounts_positive", "fact_payments",
          "SELECT COUNT(*) FROM fact_payments WHERE amount < 0", 0, "error",
          "Payment amounts must be non-negative"),
    Check("no_orphan_payments", "fact_payments",
          "SELECT COUNT(*) FROM fact_payments p LEFT JOIN fact_orders o "
          "ON p.order_key = o.order_key WHERE o.order_key IS NULL", 0, "error",
          "Payments must resolve to an order"),
    Check("no_orphan_shipments", "fact_shipments",
          "SELECT COUNT(*) FROM fact_shipments s LEFT JOIN fact_orders o "
          "ON s.order_key = o.order_key WHERE o.order_key IS NULL", 0, "error",
          "Shipments must resolve to an order"),
    Check("no_orphan_returns", "fact_returns",
          "SELECT COUNT(*) FROM fact_returns r LEFT JOIN fact_orders o "
          "ON r.order_key = o.order_key WHERE o.order_key IS NULL", 0, "error",
          "Returns must resolve to an order"),
    Check("returns_positive_quantity", "fact_returns",
          "SELECT COUNT(*) FROM fact_returns WHERE quantity <= 0 OR refund_amount < 0",
          0, "error", "Return quantities and refunds must be positive"),
    Check("customer_scd2_single_current", "dim_customer",
          "SELECT COUNT(*) FROM (SELECT customer_id FROM dim_customer "
          "WHERE is_current = TRUE GROUP BY customer_id HAVING COUNT(*) > 1) t",
          0, "error", "Exactly one current SCD2 version per customer"),
    Check("product_scd2_single_current", "dim_product",
          "SELECT COUNT(*) FROM (SELECT product_id FROM dim_product "
          "WHERE is_current = TRUE GROUP BY product_id HAVING COUNT(*) > 1) t",
          0, "error", "Exactly one current SCD2 version per product"),
    Check("dim_customer_not_empty", "dim_customer",
          "SELECT CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END FROM dim_customer", 0, "error",
          "Customer dimension must be populated"),
    Check("fresh_ingestion", "pipeline",
          "SELECT CASE WHEN MAX(ingested_at) IS NULL THEN 1 "
          "WHEN MAX(ingested_at) < :cutoff THEN 1 ELSE 0 END FROM fact_orders",
          0, "warn", "Warehouse data must be refreshed within SLA"),
]


def run_quality_checks(run_id: int | None = None) -> dict:
    """Execute every check, persist results, and compute the composite score."""
    engine = get_engine()
    results: list[dict] = []
    total_checked = 0
    total_failed = 0

    with engine.begin() as conn:
        counts = {}
        for t in ("fact_orders", "fact_order_items", "fact_payments",
                  "fact_shipments", "fact_returns", "dim_customer", "dim_product"):
            counts[t] = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0

        for chk in CHECKS:
            params = {"cutoff": datetime.utcnow() - pd.Timedelta(days=3)}
            try:
                failed = int(conn.execute(text(chk.sql), params).scalar() or 0)
            except Exception as exc:  # a broken check must not break the pipeline
                failed = -1
                results.append({
                    "check_name": chk.name, "entity": chk.entity, "status": "error",
                    "metric": -1, "threshold": chk.threshold, "rows_failed": -1,
                    "message": f"check execution error: {exc}", "created_at": datetime.utcnow(),
                })
                continue

            if failed == 0:
                status = "pass"
            else:
                status = "fail" if chk.severity == "error" else "warning"

            denom = counts.get(chk.entity, 0) or 1
            total_checked += denom
            total_failed += max(failed, 0)

            results.append({
                "check_name": chk.name, "entity": chk.entity, "status": status,
                "metric": float(failed), "threshold": float(chk.threshold),
                "rows_failed": failed, "message": chk.description,
                "created_at": datetime.utcnow(),
            })

        if run_id is not None:
            for r in results:
                r["run_id"] = run_id

        pd.DataFrame(results).to_sql("data_quality_results", conn, if_exists="append",
                                     index=False)

    passed = sum(1 for r in results if r["status"] == "pass")
    warned = sum(1 for r in results if r["status"] == "warning")
    failed_checks = sum(1 for r in results if r["status"] in ("fail", "error"))
    check_pass_rate = passed / max(len(results), 1)
    row_integrity = 1 - (total_failed / max(total_checked, 1))
    score = round((0.6 * row_integrity + 0.4 * check_pass_rate) * 100, 2)
    score = max(0.0, min(100.0, score))

    return {
        "run_id": run_id,
        "score": score,
        "checks_total": len(results),
        "checks_passed": passed,
        "checks_warned": warned,
        "checks_failed": failed_checks,
        "rows_checked": total_checked,
        "rows_failed": total_failed,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "results": results,
    }


def latest_quality_summary() -> dict:
    engine = get_engine()
    with engine.connect() as conn:
        df = pd.read_sql(text(
            "SELECT * FROM data_quality_results WHERE id IN ("
            " SELECT MAX(id) FROM data_quality_results GROUP BY check_name)"), conn)
        if df.empty:
            return {"score": 0, "checks_total": 0, "checks_passed": 0,
                    "checks_failed": 0, "results": []}
        passed = int((df["status"] == "pass").sum())
        failed = int(df["status"].isin(["fail", "error"]).sum())
        warned = int((df["status"] == "warning").sum())
        score = round((0.6 + 0.4 * (passed / max(len(df), 1))) * 100, 2) if passed else 0.0
        return {
            "score": score,
            "checks_total": len(df),
            "checks_passed": passed,
            "checks_warned": warned,
            "checks_failed": failed,
            "results": df.sort_values(["status", "check_name"]).to_dict(orient="records"),
        }


def write_quality_report(path) -> str:
    summary = run_quality_checks()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return str(path)
