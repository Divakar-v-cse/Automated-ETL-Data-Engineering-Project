"""Sales / customer / product / order analytics endpoints.

Every figure is a live aggregate over the warehouse marts or the fact tables.
Predicted values (CLV, forecast) are always labelled as predictions.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.app.db import one, rows, scalar
from backend.app.schemas import (CustomerAnalyticsResponse, OrderExplorerResponse,
                                 ProductAnalyticsResponse, SalesAnalyticsResponse)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

ORDER_SORT_COLUMNS = {
    "order_ts": "f.order_ts",
    "total_amount": "f.total_amount",
    "discount_amount": "f.discount_amount",
    "item_count": "f.item_count",
    "customer_name": "f.customer_key",
    "status": "f.status",
}
PRODUCT_SORT_COLUMNS = {
    "revenue": "revenue",
    "units": "units",
    "orders": "orders",
    "return_rate_pct": "return_rate_pct",
    "unit_price": "unit_price",
    "revenue_rank": "revenue_rank",
}
CLV_SORT_COLUMNS = {
    "predicted_clv": "predicted_clv",
    "historical_revenue": "historical_revenue",
    "orders": "orders",
    "avg_order_value": "avg_order_value",
}


def _pct(num: float | None, den: float | None) -> float | None:
    if not num or not den:
        return None
    return round(num / den * 100, 2)


def _pages(total: int, page_size: int) -> int:
    return max(1, -(-total // page_size)) if total else 0


# ------------------------------------------------------------------- sales
@router.get("/sales", response_model=SalesAnalyticsResponse,
            summary="Revenue, margin, category, region, channel and discount analysis")
def sales(
    days: int = Query(180, ge=7, le=1000, description="Daily grain window"),
    months: int = Query(24, ge=3, le=60, description="Monthly grain window"),
    top: int = Query(10, ge=3, le=50, description="Top-N product list size"),
) -> SalesAnalyticsResponse:
    last_day = scalar("SELECT MAX(order_date) FROM mart_sales_daily")
    last_day_date = date.fromisoformat(str(last_day)[:10]) if last_day else None

    summary = one(
        "SELECT SUM(revenue) AS revenue, SUM(orders) AS orders, "
        "       SUM(discount_amount) AS discount, SUM(gross_revenue) AS gross, "
        "       SUM(shipping_revenue) AS shipping, SUM(units) AS units "
        "FROM mart_sales_daily WHERE order_date >= :a",
        {"a": (last_day_date - timedelta(days=days - 1)).isoformat() if last_day_date else "1900-01-01"},
    ) or {}
    summary["avg_order_value"] = round(
        (summary.get("revenue") or 0) / (summary.get("orders") or 1), 2)
    summary["discount_pct"] = _pct(summary.get("discount"), summary.get("gross"))
    summary["revenue_per_day"] = round(
        (summary.get("revenue") or 0) / max(days, 1), 2)

    daily = rows(
        "SELECT order_date, orders, customers, revenue, units, avg_order_value, "
        "       discount_amount, discount_pct, revenue_7d_ma, revenue_30d_ma "
        "FROM mart_sales_daily WHERE order_date >= :a ORDER BY order_date",
        {"a": (last_day_date - timedelta(days=days - 1)).isoformat()} if last_day_date else {"a": "1900-01-01"},
    )
    monthly = rows(
        "SELECT period, period_start, orders, customers, revenue, units, "
        "       avg_order_value, revenue_growth_pct, revenue_yoy_pct "
        "FROM mart_sales_monthly ORDER BY period DESC LIMIT :n",
        {"n": months},
    )
    monthly.reverse()

    by_category = rows(
        "SELECT category, orders, products, units, revenue, avg_unit_price, "
        "       avg_discount_pct, returned_units, refunds, revenue_share_pct, return_rate_pct "
        "FROM mart_category_performance ORDER BY revenue DESC"
    )
    by_region = rows(
        "SELECT region, orders, customers, revenue, avg_order_value, "
        "       revenue_share_pct, revenue_per_customer "
        "FROM mart_region_performance ORDER BY revenue DESC"
    )
    by_channel = rows(
        "SELECT channel, orders, customers, revenue, avg_order_value, revenue_share_pct "
        "FROM mart_channel_performance ORDER BY revenue DESC"
    )
    top_products = rows(
        "SELECT product_id, product_name, category, brand, units, revenue, "
        "       avg_discount_pct, return_rate_pct, revenue_rank "
        "FROM mart_product_performance ORDER BY revenue DESC LIMIT :n",
        {"n": top},
    )
    discount_impact = rows(
        "SELECT discount_bucket, lines, units, revenue, avg_discount_pct, "
        "       avg_unit_price, avg_line_value FROM mart_discount_impact"
    )
    payment_methods = rows(
        "SELECT payment_method, provider, method_group, attempts, successes, failures, "
        "       settled_amount, success_rate_pct FROM mart_payment_methods "
        "ORDER BY settled_amount DESC"
    )
    forecast = rows(
        "SELECT ds, y_actual, y_forecast, y_lower, y_upper, kind, model_name "
        "FROM mart_sales_forecast ORDER BY ds, kind"
    )
    horizon = sum(1 for f in forecast if f["kind"] == "forecast")
    summary["forecast_days"] = horizon
    summary["forecast_model"] = forecast[0]["model_name"] if forecast else None

    return SalesAnalyticsResponse(
        summary=summary, daily=daily, monthly=monthly, by_category=by_category,
        by_region=by_region, by_channel=by_channel, top_products=top_products,
        discount_impact=discount_impact, payment_methods=payment_methods,
        forecast=forecast,
    )


# ---------------------------------------------------------------- customers
@router.get("/customers", response_model=CustomerAnalyticsResponse,
            summary="New vs returning, CLV, RFM, retention")
def customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    sort_by: str = Query("predicted_clv"),
) -> CustomerAnalyticsResponse:
    sort_col = CLV_SORT_COLUMNS.get(sort_by, "predicted_clv")
    cohorted = one(
        "SELECT COUNT(*) AS purchasing_customers, "
        "       SUM(CASE WHEN orders > 1 THEN 1 ELSE 0 END) AS repeat_customers, "
        "       AVG(predicted_clv) AS avg_predicted_clv, "
        "       SUM(predicted_clv) AS total_predicted_clv, "
        "       AVG(historical_revenue) AS avg_historical_revenue, "
        "       SUM(historical_revenue) AS historical_revenue, "
        "       AVG(orders) AS avg_orders "
        "FROM mart_customer_clv"
    ) or {}
    totals = one("SELECT COUNT(*) AS total FROM dim_customer WHERE is_current IS TRUE") or {}
    last_day = scalar("SELECT MAX(order_date) FROM mart_sales_daily")
    last_day_date = date.fromisoformat(str(last_day)[:10]) if last_day else None

    new_30d = None
    if last_day_date:
        new_30d = scalar(
            "SELECT COUNT(*) FROM ("
            "  SELECT customer_key, MIN(d.full_date) AS first_date "
            "  FROM fact_orders f JOIN dim_date d ON f.date_key = d.date_key "
            "  WHERE f.status <> 'cancelled' GROUP BY customer_key"
            ") t WHERE t.first_date >= :a",
            {"a": (last_day_date - timedelta(days=29)).isoformat()},
        )
    at_risk = scalar(
        "SELECT COUNT(*) FROM mart_customer_rfm WHERE rfm_segment LIKE 'At Risk%'")

    # Activity per month comes from the pre-aggregated sales mart; first-purchase
    # months come from the CLV mart. Joining two small aggregates is far cheaper
    # (and no less accurate) than COUNT(DISTINCT) over the whole fact table.
    activity = rows(
        "SELECT period, orders, customers AS active_customers, revenue "
        "FROM mart_sales_monthly ORDER BY period"
    )
    firsts = {
        r["period"]: int(r["new_customers"] or 0)
        for r in rows(
            "SELECT substr(first_order_date, 1, 7) AS period, COUNT(*) AS new_customers "
            "FROM mart_customer_clv GROUP BY substr(first_order_date, 1, 7)"
        )
    }
    new_vs_returning = []
    for item in activity:
        period = str(item["period"])
        year, month = int(period[:4]), int(period[5:7])
        new_count = firsts.get(period, 0)
        active = int(item["active_customers"] or 0)
        new_vs_returning.append({
            "period": period,
            "year": year,
            "month": month,
            "orders": item["orders"],
            "revenue": item["revenue"],
            "active_customers": active,
            "new_customers": new_count,
            "returning_customers": max(active - new_count, 0),
        })

    rfm_segments = rows(
        "SELECT rfm_segment, COUNT(*) AS customers, SUM(monetary) AS revenue, "
        "       AVG(monetary) AS avg_monetary, AVG(recency_days) AS avg_recency_days, "
        "       AVG(frequency) AS avg_frequency, AVG(rfm_score) AS avg_rfm_score "
        "FROM mart_customer_rfm GROUP BY rfm_segment ORDER BY revenue DESC"
    )
    total_customers = sum((s["customers"] or 0) for s in rfm_segments) or 1
    for s in rfm_segments:
        s["customer_share_pct"] = round((s["customers"] or 0) / total_customers * 100, 2)

    retention = rows(
        "SELECT cohort_month, month_index, cohort_size, active_customers, retention_rate_pct "
        "FROM mart_customer_retention WHERE month_index <= 12 "
        "ORDER BY cohort_month, month_index"
    )
    clv_distribution = rows(
        "SELECT clv_band, COUNT(*) AS customers, SUM(predicted_clv) AS predicted_clv, "
        "       AVG(predicted_clv) AS avg_predicted_clv, "
        "       SUM(historical_revenue) AS historical_revenue "
        "FROM mart_customer_clv GROUP BY clv_band ORDER BY MIN(predicted_clv)"
    )

    total = int(scalar("SELECT COUNT(*) FROM mart_customer_clv") or 0)
    offset = (page - 1) * page_size
    top = rows(
        f"SELECT customer_id, full_name, region, segment, orders, avg_order_value, "
        f"       historical_revenue, predicted_clv, clv_band, orders_per_year, "
        f"       recency_days, first_order_date, last_order_date, clv_model "
        f"FROM mart_customer_clv ORDER BY {sort_col} DESC LIMIT :limit OFFSET :offset",
        {"limit": page_size, "offset": offset},
    )

    return CustomerAnalyticsResponse(
        summary={
            "total_customers": totals.get("total"),
            "purchasing_customers": cohorted.get("purchasing_customers"),
            "new_customers_30d": new_30d,
            "repeat_customers": cohorted.get("repeat_customers"),
            "repeat_purchase_rate": _pct(cohorted.get("repeat_customers"),
                                         cohorted.get("purchasing_customers")),
            "avg_orders_per_customer": round(cohorted.get("avg_orders") or 0, 2),
            "avg_predicted_clv": round(cohorted.get("avg_predicted_clv") or 0, 2),
            "total_predicted_clv": round(cohorted.get("total_predicted_clv") or 0, 2),
            "historical_revenue": round(cohorted.get("historical_revenue") or 0, 2),
            "at_risk_customers": at_risk,
            "clv_note": "predicted_clv is a model estimate (AOV x cadence x 2 years, "
                        "discounted 10%); historical_revenue is realised revenue.",
        },
        new_vs_returning=new_vs_returning,
        rfm_segments=rfm_segments,
        top_customers={
            "items": top, "page": page, "page_size": page_size, "total": total,
            "pages": _pages(total, page_size), "sort_by": sort_by,
        },
        retention=retention,
        clv_distribution=clv_distribution,
    )


# ----------------------------------------------------------------- products
@router.get("/products", response_model=ProductAnalyticsResponse,
            summary="Product revenue, volume, return rates and category performance")
def products(
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=1, le=100),
    sort_by: str = Query("revenue"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    category: str | None = None,
    q: str | None = Query(None, max_length=80, description="Name / brand search"),
) -> ProductAnalyticsResponse:
    sort_col = PRODUCT_SORT_COLUMNS.get(sort_by, "revenue")
    direction = "ASC" if sort_order.lower() == "asc" else "DESC"
    where, params = [], {}
    if category:
        where.append("category = :category")
        params["category"] = category
    if q:
        where.append("(LOWER(product_name) LIKE :q OR LOWER(brand) LIKE :q "
                     "OR LOWER(product_id) LIKE :q)")
        params["q"] = f"%{q.lower()}%"
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    total = int(scalar(f"SELECT COUNT(*) FROM mart_product_performance {clause}", params) or 0)
    items = rows(
        f"SELECT product_id, product_name, category, subcategory, brand, unit_price, "
        f"       orders, units, revenue, avg_discount_pct, returned_units, refunds, "
        f"       return_rate_pct, revenue_rank "
        f"FROM mart_product_performance {clause} "
        f"ORDER BY {sort_col} {direction}, product_id LIMIT :limit OFFSET :offset",
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    )

    summary = one(
        "SELECT COUNT(*) AS products, SUM(revenue) AS revenue, SUM(units) AS units, "
        "       SUM(returned_units) AS returned_units, SUM(refunds) AS refunds, "
        "       AVG(unit_price) AS avg_unit_price "
        "FROM mart_product_performance"
    ) or {}
    summary["categories"] = scalar("SELECT COUNT(DISTINCT category) FROM mart_product_performance")
    summary["return_rate_pct"] = _pct(summary.get("returned_units"), summary.get("units"))

    return ProductAnalyticsResponse(
        summary=summary,
        products={
            "items": items, "page": page, "page_size": page_size, "total": total,
            "pages": _pages(total, page_size), "sort_by": sort_by,
            "sort_order": sort_order, "filters": {"category": category, "q": q},
        },
        by_category=rows(
            "SELECT category, orders, products, units, revenue, avg_unit_price, "
            "       avg_discount_pct, returned_units, refunds, revenue_share_pct, "
            "       return_rate_pct FROM mart_category_performance ORDER BY revenue DESC"
        ),
        best_sellers=rows(
            "SELECT product_id, product_name, category, brand, units, revenue, "
            "       return_rate_pct FROM mart_product_performance "
            "ORDER BY units DESC, revenue DESC LIMIT 10"
        ),
        worst_return_rates=rows(
            "SELECT product_id, product_name, category, units, returned_units, "
            "       return_rate_pct, revenue FROM mart_product_performance "
            "WHERE units >= 20 ORDER BY return_rate_pct DESC, units DESC LIMIT 10"
        ),
    )


# ------------------------------------------------------------------- orders
@router.get("/orders", response_model=OrderExplorerResponse,
            summary="Paginated order explorer with filters")
def orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    q: str | None = Query(None, max_length=60, description="Order / customer search"),
    status: str | None = Query(None, max_length=24),
    channel: str | None = Query(None, max_length=40),
    region: str | None = Query(None, max_length=80),
    customer_id: str | None = Query(None, max_length=32),
    date_from: date | None = None,
    date_to: date | None = None,
    min_total: float | None = Query(None, ge=0),
    max_total: float | None = Query(None, ge=0),
    sort_by: str = Query("order_ts"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
) -> OrderExplorerResponse:
    if date_from and date_to and date_to < date_from:
        raise HTTPException(status_code=422, detail="date_to must be on or after date_from")

    where = ["1 = 1"]
    params: dict[str, Any] = {}
    if q:
        where.append(
            "(LOWER(f.order_id) LIKE :q OR f.customer_key IN ("
            "  SELECT customer_key FROM dim_customer"
            "  WHERE LOWER(full_name) LIKE :q OR LOWER(customer_id) LIKE :q))"
        )
        params["q"] = f"%{q.lower()}%"
    if status:
        where.append("f.status = :status")
        params["status"] = status
    if channel:
        where.append("f.channel = :channel")
        params["channel"] = channel
    if region or customer_id:
        # only join the customer dimension when the filter actually needs it
        where.append(
            "f.customer_key IN (SELECT customer_key FROM dim_customer c2 WHERE "
            + " AND ".join(
                [x for x in [
                    "c2.region = :region" if region else None,
                    "c2.customer_id = :customer_id" if customer_id else None,
                ] if x]
            )
            + ")"
        )
        if region:
            params["region"] = region
        if customer_id:
            params["customer_id"] = customer_id
    if date_from:
        where.append("f.order_ts >= :date_from")
        params["date_from"] = f"{date_from.isoformat()} 00:00:00"
    if date_to:
        where.append("f.order_ts <= :date_to")
        params["date_to"] = f"{date_to.isoformat()} 23:59:59"
    if min_total is not None:
        where.append("f.total_amount >= :min_total")
        params["min_total"] = min_total
    if max_total is not None:
        where.append("f.total_amount <= :max_total")
        params["max_total"] = max_total

    clause = " AND ".join(where)
    sort_col = ORDER_SORT_COLUMNS.get(sort_by, "f.order_ts").replace("d.full_date", "f.order_ts")
    direction = "ASC" if sort_order.lower() == "asc" else "DESC"
    # No dimension joins in the hot path: the fact table is scanned once for the
    # page, once for the count and once for the summary instead of joining 99k
    # orders against 20k customers three times per keystroke.
    base = f"FROM fact_orders f WHERE {clause}"
    total = int(scalar(f"SELECT COUNT(*) {base}", params) or 0)
    items = rows(
        "SELECT f.order_id, f.status, f.channel, f.currency, f.product_count, "
        "       f.item_count, f.order_amount, f.discount_amount, f.shipping_cost, "
        "       f.total_amount, f.order_ts, f.updated_at, f.customer_key, "
        "       substr(f.order_ts, 1, 10) AS order_date "
        f"{base} ORDER BY {sort_col} {direction}, f.order_id LIMIT :limit OFFSET :offset",
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    )
    if items:
        keys = [r["customer_key"] for r in items if r.get("customer_key") is not None]
        if keys:
            placeholders = ", ".join(f":k{i}" for i in range(len(keys)))
            dims = {
                r["customer_key"]: r
                for r in rows(
                    "SELECT customer_key, customer_id, full_name, country, region, segment "
                    f"FROM dim_customer WHERE customer_key IN ({placeholders})",
                    {f"k{i}": k for i, k in enumerate(keys)},
                )
            }
            for r in items:
                dim = dims.get(r.get("customer_key"), {})
                r["customer_id"] = dim.get("customer_id")
                r["customer_name"] = dim.get("full_name")
                r["country"] = dim.get("country")
                r["region"] = dim.get("region")
                r["segment"] = dim.get("segment")
    summary = one(
        "SELECT COUNT(*) AS orders, SUM(f.total_amount) AS revenue, "
        "       AVG(f.total_amount) AS avg_order_value, SUM(f.item_count) AS units, "
        "       SUM(f.discount_amount) AS discount "
        f"{base}", params,
    ) or {}

    return OrderExplorerResponse(
        items=items, page=page, page_size=page_size, total=total,
        pages=_pages(total, page_size),
        filters={
            "q": q, "status": status, "channel": channel, "region": region,
            "customer_id": customer_id,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "min_total": min_total, "max_total": max_total,
            "sort_by": sort_by, "sort_order": sort_order,
        },
        summary=summary,
    )


@router.get("/orders/{order_id}", summary="Full order detail (items, payments, shipments, returns)")
def order_detail(order_id: str) -> dict:
    header = one(
        "SELECT f.order_id, f.status, f.channel, f.currency, f.order_amount, "
        "       f.discount_amount, f.shipping_cost, f.total_amount, f.order_ts, "
        "       d.full_date AS order_date, c.customer_id, c.full_name AS customer_name, "
        "       c.email, c.country, c.region, c.segment "
        "FROM fact_orders f JOIN dim_date d ON d.date_key = f.date_key "
        "LEFT JOIN dim_customer c ON c.customer_key = f.customer_key "
        "WHERE f.order_id = :oid", {"oid": order_id},
    )
    if not header:
        raise HTTPException(status_code=404, detail=f"order {order_id} not found")
    return {
        "order": header,
        "items": rows(
            "SELECT i.order_item_id, p.product_id, p.product_name, p.category, "
            "       i.quantity, i.unit_price, i.discount_pct, i.line_total "
            "FROM fact_order_items i LEFT JOIN dim_product p ON p.product_key = i.product_key "
            "WHERE i.order_id = :oid ORDER BY i.order_item_id", {"oid": order_id}),
        "payments": rows(
            "SELECT pay.payment_id, pm.payment_method, pm.provider, pay.amount, "
            "       pay.status, pay.paid_at FROM fact_payments pay "
            "LEFT JOIN dim_payment pm ON pm.payment_method_key = pay.payment_method_key "
            "WHERE pay.order_id = :oid", {"oid": order_id}),
        "shipments": rows(
            "SELECT shipment_id, carrier, tracking_number, status, shipped_at, "
            "       delivered_at, shipping_cost FROM fact_shipments WHERE order_id = :oid",
            {"oid": order_id}),
        "returns": rows(
            "SELECT r.return_id, p.product_id, p.product_name, r.quantity, r.reason, "
            "       r.refund_amount, r.status, r.returned_at FROM fact_returns r "
            "LEFT JOIN dim_product p ON p.product_key = r.product_key "
            "WHERE r.order_id = :oid", {"oid": order_id}),
        "generated_at": datetime.utcnow().isoformat(),
    }

