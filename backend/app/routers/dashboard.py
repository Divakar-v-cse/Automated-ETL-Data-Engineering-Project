"""GET /api/dashboard/overview - executive KPIs, all computed from the warehouse."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter

from backend.app.db import one, rows, scalar
from backend.app.schemas import OverviewResponse

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _pct(num: float | None, den: float | None) -> float | None:
    if not num or not den:
        return None
    return round(num / den * 100, 2)


def _latest_fact_date() -> date | None:
    value = scalar("SELECT MAX(order_date) FROM mart_sales_daily")
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


@router.get("/overview", response_model=OverviewResponse,
            summary="Executive dashboard metrics")
def overview(trend_days: int = 90) -> OverviewResponse:
    trend_days = max(7, min(trend_days, 365))
    totals = one(
        "SELECT COUNT(*) AS orders, COUNT(DISTINCT customer_key) AS buyers, "
        "       SUM(total_amount) AS revenue, SUM(discount_amount) AS discount, "
        "       SUM(item_count) AS units, AVG(total_amount) AS aov "
        "FROM fact_orders WHERE status <> 'cancelled'"
    ) or {}
    payments = one(
        "SELECT COUNT(*) AS attempts, "
        "       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes, "
        "       SUM(CASE WHEN status = 'success' THEN amount ELSE 0 END) AS settled "
        "FROM fact_payments"
    ) or {}
    returns = one(
        "SELECT COUNT(DISTINCT order_id) AS returned_orders, "
        "       SUM(refund_amount) AS refunds FROM fact_returns"
    ) or {}
    customers = one(
        "SELECT COUNT(*) AS total FROM dim_customer WHERE is_current IS TRUE"
    ) or {}
    repeat = one(
        "SELECT SUM(CASE WHEN orders > 1 THEN 1 ELSE 0 END) AS repeat_customers, "
        "       COUNT(*) AS purchasing_customers FROM mart_customer_clv"
    ) or {}

    last_day = _latest_fact_date()
    growth = None
    previous = None
    current_window = None
    if last_day:
        start = last_day - timedelta(days=29)
        prev_start = start - timedelta(days=30)
        prev_end = start - timedelta(days=1)
        current_window = one(
            "SELECT SUM(revenue) AS revenue, SUM(orders) AS orders "
            "FROM mart_sales_daily WHERE order_date BETWEEN :a AND :b",
            {"a": start.isoformat(), "b": last_day.isoformat()},
        ) or {}
        previous = one(
            "SELECT SUM(revenue) AS revenue, SUM(orders) AS orders "
            "FROM mart_sales_daily WHERE order_date BETWEEN :a AND :b",
            {"a": prev_start.isoformat(), "b": prev_end.isoformat()},
        ) or {}
        if previous.get("revenue"):
            growth = round(
                (current_window.get("revenue") or 0) / previous["revenue"] * 100 - 100, 2
            )

    active = scalar(
        "SELECT COUNT(DISTINCT customer_key) FROM fact_orders WHERE order_ts >= :cut",
        {"cut": (datetime.utcnow() - timedelta(days=30)).isoformat(sep=" ")},
    )
    latest_run = one(
        "SELECT run_id, dag_id, status, trigger, started_at, finished_at, "
        "       duration_seconds, records_extracted, records_transformed, "
        "       records_loaded, records_rejected, quality_score "
        "FROM pipeline_runs ORDER BY run_id DESC LIMIT 1"
    )
    runs_window = rows(
        "SELECT status FROM pipeline_runs ORDER BY run_id DESC LIMIT 20"
    )
    ok_runs = sum(1 for r in runs_window if r["status"] == "success")

    last_ingest = scalar("SELECT MAX(ingested_at) FROM fact_orders")
    freshness_minutes = None
    if last_ingest:
        try:
            stamp = datetime.fromisoformat(str(last_ingest).replace("Z", ""))
            freshness_minutes = round((datetime.utcnow() - stamp).total_seconds() / 60, 1)
        except ValueError:
            freshness_minutes = None

    # ------------------------------------------------------------- detail lists
    trend_start = (last_day - timedelta(days=trend_days - 1)).isoformat() if last_day else None
    revenue_trend = rows(
        "SELECT order_date, orders, revenue, avg_order_value, revenue_7d_ma, "
        "       revenue_30d_ma, discount_pct "
        "FROM mart_sales_daily WHERE order_date >= :a ORDER BY order_date",
        {"a": trend_start or "1900-01-01"},
    ) if last_day else []
    monthly = rows(
        "SELECT period, period_start, orders, customers, revenue, avg_order_value, "
        "       revenue_growth_pct, revenue_yoy_pct "
        "FROM mart_sales_monthly ORDER BY period DESC LIMIT 18"
    )
    monthly.reverse()

    top_categories = rows(
        "SELECT category, orders, units, revenue, revenue_share_pct, return_rate_pct "
        "FROM mart_category_performance ORDER BY revenue DESC LIMIT 6"
    )
    channel_mix = rows(
        "SELECT channel, orders, customers, revenue, revenue_share_pct, avg_order_value "
        "FROM mart_channel_performance ORDER BY revenue DESC"
    )
    recent_runs = rows(
        "SELECT run_id, dag_id, status, trigger, started_at, finished_at, "
        "       duration_seconds, records_loaded, records_rejected, quality_score "
        "FROM pipeline_runs ORDER BY run_id DESC LIMIT 5"
    )

    from etl.transform.quality import latest_quality_summary
    quality = latest_quality_summary()

    return OverviewResponse(
        generated_at=datetime.utcnow(),
        kpis={
            "total_revenue": totals.get("revenue"),
            "total_orders": totals.get("orders"),
            "avg_order_value": round(totals["aov"], 2) if totals.get("aov") else None,
            "total_customers": customers.get("total"),
            "active_customers_30d": active,
            "total_units": totals.get("units"),
            "total_discount": totals.get("discount"),
            "payment_success_rate": _pct(payments.get("successes"), payments.get("attempts")),
            "payment_attempts": payments.get("attempts"),
            "settled_amount": payments.get("settled"),
            "return_rate": _pct(returns.get("returned_orders"), totals.get("orders")),
            "returned_orders": returns.get("returned_orders"),
            "total_refunds": returns.get("refunds"),
            "repeat_purchase_rate": _pct(repeat.get("repeat_customers"),
                                         repeat.get("purchasing_customers")),
            "repeat_customers": repeat.get("repeat_customers"),
            "revenue_growth_pct": growth,
            "revenue_last_30d": (current_window or {}).get("revenue"),
            "revenue_prev_30d": (previous or {}).get("revenue"),
            "reporting_through": last_day.isoformat() if last_day else None,
            "pipeline_success_rate": _pct(ok_runs, len(runs_window)),
            "last_successful_run": (latest_run or {}).get("finished_at"),
        },
        revenue_trend=revenue_trend,
        monthly_revenue=monthly,
        top_categories=top_categories,
        channel_mix=channel_mix,
        recent_runs=recent_runs,
        quality={
            "score": quality.get("score"),
            "checks_total": quality.get("checks_total"),
            "checks_passed": quality.get("checks_passed"),
            "checks_failed": quality.get("checks_failed"),
        },
        pipeline={
            "latest_run": latest_run,
            "status": (latest_run or {}).get("status", "never_run"),
            "freshness_minutes": freshness_minutes,
            "last_ingested_at": last_ingest,
        },
    )
