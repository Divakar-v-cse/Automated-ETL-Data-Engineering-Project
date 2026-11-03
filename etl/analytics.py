"""Analytics mart layer.

Builds the analytics-ready tables that back the dashboard and the API.  Every
mart is recomputed from the warehouse facts with plain SQL + pandas so the same
code runs on PostgreSQL (production) and SQLite (local functional equivalent).

Marts produced
--------------
``mart_sales_daily``            daily revenue / orders / AOV / units
``mart_sales_monthly``          monthly revenue with month-over-month growth
``mart_category_performance``   revenue, units and return rate per category
``mart_region_performance``     revenue per customer region
``mart_product_performance``    per-product revenue, volume, returns
``mart_channel_performance``    revenue split by sales channel
``mart_discount_impact``        revenue vs discount depth
``mart_payment_methods``        payment success rate per method
``mart_customer_rfm``           RFM scores + segment label
``mart_customer_clv``           historical and predicted lifetime value
``mart_customer_retention``     monthly acquisition cohorts and retention
``mart_sales_forecast``         actual vs forecast daily revenue

Forecast rows carry ``kind = 'forecast'`` and a model name so the UI can always
distinguish predictions from realised actuals.
"""
from __future__ import annotations

import json
from datetime import date, datetime

import numpy as np
import pandas as pd
from sqlalchemy import text

from etl.db import get_engine
from etl.logging_config import get_logger

log = get_logger("etl.analytics")

FORECAST_HORIZON = 30          # days ahead
FORECAST_MIN_HISTORY = 60      # need enough daily points for a sane fit


# --------------------------------------------------------------------- helpers
def _read(sql: str, params: dict | None = None) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def _write(df: pd.DataFrame, table: str) -> int:
    """Replace a mart table with ``df`` and return the row count."""
    if df is None:
        return 0
    with get_engine().begin() as conn:
        df.to_sql(table, conn, if_exists="replace", index=False)
    return len(df)


def _q(engine, sql: str, params: dict | None = None):
    with engine.connect() as conn:
        return conn.execute(text(sql), params or {}).scalar()


# ------------------------------------------------------------------ sales marts
def build_sales_daily() -> int:
    df = _read("""
        SELECT d.full_date                         AS order_date,
               COUNT(DISTINCT f.order_id)          AS orders,
               COUNT(DISTINCT f.customer_key)      AS customers,
               SUM(f.total_amount)                 AS revenue,
               SUM(f.discount_amount)               AS discount_amount,
               SUM(f.order_amount)                 AS gross_revenue,
               SUM(f.shipping_cost)                AS shipping_revenue,
               SUM(f.item_count)                   AS units,
               CASE WHEN COUNT(DISTINCT f.order_id) > 0
                    THEN SUM(f.total_amount) * 1.0 / COUNT(DISTINCT f.order_id)
                    ELSE 0 END                     AS avg_order_value
        FROM fact_orders f
        JOIN dim_date d ON f.date_key = d.date_key
        WHERE f.status <> 'cancelled'
        GROUP BY d.full_date
        ORDER BY d.full_date
    """)
    if df.empty:
        return _write(df, "mart_sales_daily")
    df["order_date"] = pd.to_datetime(df["order_date"])
    for c in ("revenue", "discount_amount", "gross_revenue", "shipping_revenue",
              "avg_order_value"):
        df[c] = pd.to_numeric(df[c], errors="coerce").round(2)
    df["discount_pct"] = np.where(df["gross_revenue"] > 0,
                                  df["discount_amount"] / df["gross_revenue"] * 100, 0).round(2)
    df["revenue_7d_ma"] = df["revenue"].rolling(7, min_periods=1).mean().round(2)
    df["revenue_30d_ma"] = df["revenue"].rolling(30, min_periods=1).mean().round(2)
    df["order_date"] = df["order_date"].dt.date
    return _write(df, "mart_sales_daily")


def build_sales_monthly() -> int:
    df = _read("""
        SELECT d.year, d.month,
               MIN(d.full_date)                    AS period_start,
               COUNT(DISTINCT f.order_id)          AS orders,
               COUNT(DISTINCT f.customer_key)      AS customers,
               SUM(f.total_amount)                 AS revenue,
               SUM(f.discount_amount)              AS discount_amount,
               SUM(f.item_count)                   AS units
        FROM fact_orders f
        JOIN dim_date d ON f.date_key = d.date_key
        WHERE f.status <> 'cancelled'
        GROUP BY d.year, d.month
        ORDER BY d.year, d.month
    """)
    if df.empty:
        return _write(df, "mart_sales_monthly")
    df["period"] = [f"{int(y)}-{int(m):02d}" for y, m in zip(df["year"], df["month"])]
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").round(2)
    df["avg_order_value"] = (df["revenue"] / df["orders"].replace(0, np.nan)).round(2)
    df["revenue_growth_pct"] = df["revenue"].pct_change().mul(100).round(2)
    df["revenue_yoy_pct"] = df["revenue"].pct_change(12).mul(100).round(2)
    df["period_start"] = pd.to_datetime(df["period_start"]).dt.date
    cols = ["year", "month", "period", "period_start", "orders", "customers",
            "revenue", "discount_amount", "units", "avg_order_value",
            "revenue_growth_pct", "revenue_yoy_pct"]
    return _write(df[cols], "mart_sales_monthly")


def build_category_performance() -> int:
    df = _read("""
        SELECT p.category,
               COUNT(DISTINCT i.order_id)              AS orders,
               COUNT(DISTINCT i.product_key)           AS products,
               SUM(i.quantity)                         AS units,
               SUM(i.line_total)                       AS revenue,
               AVG(i.unit_price)                       AS avg_unit_price,
               AVG(i.discount_pct)                     AS avg_discount_pct
        FROM fact_order_items i
        JOIN dim_product p ON i.product_key = p.product_key
        GROUP BY p.category
        ORDER BY revenue DESC
    """)
    if df.empty:
        return _write(df, "mart_category_performance")
    returns = _read("""
        SELECT p.category, SUM(r.quantity) AS returned_units, SUM(r.refund_amount) AS refunds
        FROM fact_returns r
        JOIN dim_product p ON r.product_key = p.product_key
        GROUP BY p.category
    """)
    df = df.merge(returns, on="category", how="left").fillna({"returned_units": 0, "refunds": 0})
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").round(2)
    df["avg_unit_price"] = pd.to_numeric(df["avg_unit_price"], errors="coerce").round(2)
    df["avg_discount_pct"] = pd.to_numeric(df["avg_discount_pct"], errors="coerce").round(2)
    df["revenue_share_pct"] = (df["revenue"] / df["revenue"].sum() * 100).round(2)
    df["return_rate_pct"] = np.where(df["units"] > 0,
                                     df["returned_units"] / df["units"] * 100, 0).round(2)
    return _write(df, "mart_category_performance")


def build_region_performance() -> int:
    df = _read("""
        SELECT c.region,
               COUNT(DISTINCT f.order_id)           AS orders,
               COUNT(DISTINCT f.customer_key)       AS customers,
               SUM(f.total_amount)                  AS revenue,
               AVG(f.total_amount)                  AS avg_order_value
        FROM fact_orders f
        JOIN dim_customer c ON f.customer_key = c.customer_key
        WHERE f.status <> 'cancelled'
        GROUP BY c.region
        ORDER BY revenue DESC
    """)
    if df.empty:
        return _write(df, "mart_region_performance")
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").round(2)
    df["avg_order_value"] = pd.to_numeric(df["avg_order_value"], errors="coerce").round(2)
    df["revenue_share_pct"] = (df["revenue"] / df["revenue"].sum() * 100).round(2)
    df["revenue_per_customer"] = (df["revenue"] / df["customers"].replace(0, np.nan)).round(2)
    return _write(df, "mart_region_performance")


def build_product_performance() -> int:
    df = _read("""
        SELECT p.product_id, p.product_name, p.category, p.subcategory, p.brand,
               p.unit_price,
               COUNT(DISTINCT i.order_id)           AS orders,
               SUM(i.quantity)                      AS units,
               SUM(i.line_total)                    AS revenue,
               AVG(i.discount_pct)                  AS avg_discount_pct
        FROM fact_order_items i
        JOIN dim_product p ON i.product_key = p.product_key
        GROUP BY p.product_id, p.product_name, p.category, p.subcategory, p.brand, p.unit_price
    """)
    if df.empty:
        return _write(df, "mart_product_performance")
    returns = _read("""
        SELECT p.product_id, SUM(r.quantity) AS returned_units, SUM(r.refund_amount) AS refunds
        FROM fact_returns r
        JOIN dim_product p ON r.product_key = p.product_key
        GROUP BY p.product_id
    """)
    df = df.merge(returns, on="product_id", how="left").fillna({"returned_units": 0, "refunds": 0})
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").round(2)
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").round(2)
    df["avg_discount_pct"] = pd.to_numeric(df["avg_discount_pct"], errors="coerce").round(2)
    df["return_rate_pct"] = np.where(df["units"] > 0,
                                     df["returned_units"] / df["units"] * 100, 0).round(2)
    df["revenue_rank"] = df["revenue"].rank(ascending=False, method="min").astype(int)
    df = df.sort_values("revenue", ascending=False).reset_index(drop=True)
    return _write(df, "mart_product_performance")


def build_channel_performance() -> int:
    df = _read("""
        SELECT f.channel,
               COUNT(DISTINCT f.order_id) AS orders,
               COUNT(DISTINCT f.customer_key) AS customers,
               SUM(f.total_amount) AS revenue,
               AVG(f.total_amount) AS avg_order_value
        FROM fact_orders f
        WHERE f.status <> 'cancelled'
        GROUP BY f.channel
        ORDER BY revenue DESC
    """)
    if df.empty:
        return _write(df, "mart_channel_performance")
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").round(2)
    df["avg_order_value"] = pd.to_numeric(df["avg_order_value"], errors="coerce").round(2)
    df["revenue_share_pct"] = (df["revenue"] / df["revenue"].sum() * 100).round(2)
    return _write(df, "mart_channel_performance")


def build_discount_impact() -> int:
    df = _read("""
        SELECT CASE
                 WHEN i.discount_pct <= 0 THEN '0% (none)'
                 WHEN i.discount_pct <= 5 THEN '0-5%'
                 WHEN i.discount_pct <= 10 THEN '5-10%'
                 WHEN i.discount_pct <= 20 THEN '10-20%'
                 ELSE '20%+'
               END AS discount_bucket,
               COUNT(*) AS lines,
               SUM(i.quantity) AS units,
               SUM(i.line_total) AS revenue,
               AVG(i.discount_pct) AS avg_discount_pct,
               AVG(i.unit_price) AS avg_unit_price
        FROM fact_order_items i
        GROUP BY 1
    """)
    if df.empty:
        return _write(df, "mart_discount_impact")
    order = ["0% (none)", "0-5%", "5-10%", "10-20%", "20%+"]
    df["bucket_order"] = df["discount_bucket"].map({b: i for i, b in enumerate(order)}).fillna(99)
    df = df.sort_values("bucket_order").drop(columns=["bucket_order"])
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").round(2)
    df["avg_discount_pct"] = pd.to_numeric(df["avg_discount_pct"], errors="coerce").round(2)
    df["avg_line_value"] = (df["revenue"] / df["lines"].replace(0, np.nan)).round(2)
    return _write(df, "mart_discount_impact")


def build_payment_methods() -> int:
    df = _read("""
        SELECT pm.payment_method, pm.provider, pm.method_group,
               COUNT(*) AS attempts,
               SUM(CASE WHEN p.status = 'success' THEN 1 ELSE 0 END) AS successes,
               SUM(CASE WHEN p.status <> 'success' THEN 1 ELSE 0 END) AS failures,
               SUM(CASE WHEN p.status = 'success' THEN p.amount ELSE 0 END) AS settled_amount
        FROM fact_payments p
        JOIN dim_payment pm ON p.payment_method_key = pm.payment_method_key
        GROUP BY pm.payment_method, pm.provider, pm.method_group
        ORDER BY settled_amount DESC
    """)
    if df.empty:
        return _write(df, "mart_payment_methods")
    df["success_rate_pct"] = (df["successes"] / df["attempts"].replace(0, np.nan) * 100).round(2)
    df["settled_amount"] = pd.to_numeric(df["settled_amount"], errors="coerce").round(2)
    return _write(df, "mart_payment_methods")


# ---------------------------------------------------------------- customer marts
def build_customer_rfm() -> int:
    df = _read("""
        SELECT f.customer_key,
               MAX(d.full_date)          AS last_order_date,
               MIN(d.full_date)          AS first_order_date,
               COUNT(DISTINCT f.order_id) AS frequency,
               SUM(f.total_amount)        AS monetary,
               AVG(f.total_amount)        AS avg_order_value
        FROM fact_orders f
        JOIN dim_date d ON f.date_key = d.date_key
        WHERE f.status <> 'cancelled'
        GROUP BY f.customer_key
    """)
    if df.empty:
        return _write(df, "mart_customer_rfm")

    dims = _read("""
        SELECT customer_key, customer_id, full_name, email, country, region, city,
               segment, signup_date
        FROM dim_customer WHERE is_current = TRUE
    """)
    df = df.merge(dims, on="customer_key", how="left")

    snapshot = pd.to_datetime(df["last_order_date"]).max()
    df["recency_days"] = (snapshot - pd.to_datetime(df["last_order_date"])).dt.days
    df["monetary"] = pd.to_numeric(df["monetary"], errors="coerce").round(2)
    df["avg_order_value"] = pd.to_numeric(df["avg_order_value"], errors="coerce").round(2)

    def _score(series: pd.Series, higher_is_better: bool, q: int = 5) -> pd.Series:
        """Quantile score 1..q; ties fall back to a rank so scores never collapse."""
        try:
            scored = pd.qcut(series.rank(method="first"), q, labels=False) + 1
        except ValueError:  # too few distinct values
            scored = pd.Series(np.full(len(series), 3))
        return scored if higher_is_better else (q + 1 - scored)

    df["r_score"] = _score(df["recency_days"], higher_is_better=False).astype(int)
    df["f_score"] = _score(df["frequency"], higher_is_better=True).astype(int)
    df["m_score"] = _score(df["monetary"], higher_is_better=True).astype(int)
    df["rfm_score"] = df["r_score"] + df["f_score"] + df["m_score"]

    def _segment(row) -> str:
        r, f, m = row["r_score"], row["f_score"], row["m_score"]
        if r >= 4 and f >= 4 and m >= 4:
            return "Champions"
        if r >= 3 and f >= 4:
            return "Loyal Customers"
        if r >= 4 and f <= 2:
            return "New / Promising"
        if r == 3 and f == 3:
            return "Need Attention"
        if r <= 2 and f >= 4:
            return "At Risk (High Value)"
        if r <= 2 and m >= 3:
            return "At Risk"
        if r <= 2:
            return "Hibernating"
        return "Others"

    df["rfm_segment"] = df.apply(_segment, axis=1)
    df["first_order_date"] = pd.to_datetime(df["first_order_date"]).dt.date
    df["last_order_date"] = pd.to_datetime(df["last_order_date"]).dt.date
    if "signup_date" in df.columns:
        df["signup_date"] = pd.to_datetime(df["signup_date"], errors="coerce").dt.date
    return _write(df, "mart_customer_rfm")


def build_customer_clv() -> int:
    df = _read("""
        SELECT f.customer_key,
               COUNT(DISTINCT f.order_id) AS orders,
               SUM(f.total_amount)        AS historical_revenue,
               AVG(f.total_amount)        AS avg_order_value,
               MIN(d.full_date)           AS first_order_date,
               MAX(d.full_date)           AS last_order_date
        FROM fact_orders f
        JOIN dim_date d ON f.date_key = d.date_key
        WHERE f.status <> 'cancelled'
        GROUP BY f.customer_key
    """)
    if df.empty:
        return _write(df, "mart_customer_clv")

    dims = _read("""SELECT customer_key, customer_id, full_name, region, segment
                    FROM dim_customer WHERE is_current = TRUE""")
    df = df.merge(dims, on="customer_key", how="left")

    first = pd.to_datetime(df["first_order_date"])
    last = pd.to_datetime(df["last_order_date"])
    snapshot = last.max()
    df["tenure_days"] = (last - first).dt.days.clip(lower=1)
    df["recency_days"] = (snapshot - last).dt.days

    # Observed purchase cadence (orders / year of tenure)
    df["orders_per_year"] = (df["orders"] / (df["tenure_days"] / 365.25)).round(3)
    df["historical_revenue"] = pd.to_numeric(df["historical_revenue"], errors="coerce").round(2)
    df["avg_order_value"] = pd.to_numeric(df["avg_order_value"], errors="coerce").round(2)

    # Predictive CLV: AOV x expected orders/year x 2-year horizon, discounted 10%/yr.
    # This is an ESTIMATE, not realised revenue.
    EXPECTED_LIFESPAN_YEARS = 2.0
    DISCOUNT_RATE = 0.10
    cadence = df["orders_per_year"].clip(lower=0.2, upper=24)
    gross = df["avg_order_value"] * cadence * EXPECTED_LIFESPAN_YEARS
    df["predicted_clv"] = (gross / (1 + DISCOUNT_RATE) ** (EXPECTED_LIFESPAN_YEARS / 2)).round(2)
    df["clv_band"] = pd.cut(df["predicted_clv"],
                            [-1, 100, 500, 2000, 5000, np.inf],
                            labels=["<100", "100-500", "500-2k", "2k-5k", "5k+"]).astype(str)
    df["is_repeat_customer"] = df["orders"] > 1
    df["first_order_date"] = first.dt.date
    df["last_order_date"] = last.dt.date
    df["clv_model"] = "aov_x_cadence_x_2y_discounted_10pct"
    return _write(df, "mart_customer_clv")


def build_customer_retention() -> int:
    base = _read("""
        SELECT f.customer_key, d.year, d.month, d.full_date
        FROM fact_orders f
        JOIN dim_date d ON f.date_key = d.date_key
        WHERE f.status <> 'cancelled'
        GROUP BY f.customer_key, d.year, d.month, d.full_date
    """)
    if base.empty:
        return _write(base, "mart_customer_retention")

    base["full_date"] = pd.to_datetime(base["full_date"])
    base["period"] = base["full_date"].dt.to_period("M")
    cohort = base.groupby("customer_key")["period"].min().rename("cohort")
    base = base.join(cohort, on="customer_key")
    base["month_index"] = ((base["period"].dt.year - base["cohort"].dt.year) * 12
                           + (base["period"].dt.month - base["cohort"].dt.month))
    base["active"] = 1

    activity = (base.groupby(["cohort", "month_index"])["customer_key"]
                    .nunique().reset_index(name="active_customers"))
    sizes = cohort.value_counts().rename("cohort_size")
    activity = activity.join(sizes, on="cohort")
    activity["retention_rate_pct"] = (activity["active_customers"]
                                      / activity["cohort_size"] * 100).round(2)
    activity["cohort_month"] = activity["cohort"].astype(str)
    out = activity.drop(columns=["cohort"]).sort_values(["cohort_month", "month_index"])
    return _write(out, "mart_customer_retention")


# -------------------------------------------------------------------- forecast
def build_sales_forecast() -> int:
    """Linear trend + weekday seasonality on daily revenue.

    Rows with ``kind='actual'`` are realised revenue; rows with
    ``kind='forecast'`` are predictions produced by ``model_name``.
    """
    daily = _read("""
        SELECT d.full_date AS ds, SUM(f.total_amount) AS y
        FROM fact_orders f JOIN dim_date d ON f.date_key = d.date_key
        WHERE f.status <> 'cancelled'
        GROUP BY d.full_date ORDER BY d.full_date
    """)
    if daily.empty or len(daily) < FORECAST_MIN_HISTORY:
        return _write(pd.DataFrame(columns=["ds", "y_actual", "y_forecast",
                                            "y_lower", "y_upper", "kind", "model_name"]),
                      "mart_sales_forecast")

    daily["ds"] = pd.to_datetime(daily["ds"])
    daily["y"] = pd.to_numeric(daily["y"], errors="coerce").fillna(0.0)
    daily = daily.sort_values("ds").reset_index(drop=True)

    # Fit on the last 180 days for responsiveness
    fit = daily.tail(180).copy().reset_index(drop=True)
    x = np.arange(len(fit), dtype=float)
    y = fit["y"].to_numpy(dtype=float)

    slope, intercept = np.polyfit(x, y, 1)
    trend = intercept + slope * x
    residual = y - trend

    # Weekday multiplicative factor from the detrended residual
    dow = fit["ds"].dt.dayofweek
    factors = pd.Series(residual).groupby(dow).mean()
    factors = (factors / max(abs(factors).mean(), 1e-9)).fillna(1.0)
    sigma = float(np.std(residual)) or float(np.std(y)) * 0.1 or 1.0

    future_dates = pd.date_range(fit["ds"].max() + pd.Timedelta(days=1),
                                 periods=FORECAST_HORIZON, freq="D")
    fx = np.arange(len(fit), len(fit) + FORECAST_HORIZON, dtype=float)
    f_trend = intercept + slope * fx
    f_dow = future_dates.dayofweek
    f_factor = f_dow.map(factors).fillna(1.0).to_numpy()
    forecast = np.clip(f_trend + f_factor * sigma * 0.5, 0, None)
    # widening confidence band the further out we go
    horizon_scale = np.sqrt(np.arange(1, FORECAST_HORIZON + 1) / 7.0)
    lower = np.clip(forecast - 1.28 * sigma * horizon_scale, 0, None)
    upper = forecast + 1.28 * sigma * horizon_scale

    actual = pd.DataFrame({
        "ds": fit["ds"], "y_actual": y.round(2), "y_forecast": trend.round(2),
        "y_lower": np.nan, "y_upper": np.nan, "kind": "actual",
        "model_name": "linear_trend_plus_weekday_seasonality",
    })
    pred = pd.DataFrame({
        "ds": future_dates, "y_actual": np.nan, "y_forecast": forecast.round(2),
        "y_lower": lower.round(2), "y_upper": upper.round(2), "kind": "forecast",
        "model_name": "linear_trend_plus_weekday_seasonality",
    })
    out = pd.concat([actual, pred], ignore_index=True)
    out["ds"] = pd.to_datetime(out["ds"]).dt.date
    out["residual_sigma"] = round(sigma, 2)
    return _write(out, "mart_sales_forecast")


# ------------------------------------------------------------------ aggregator
MARTS = [
    ("mart_sales_daily", build_sales_daily),
    ("mart_sales_monthly", build_sales_monthly),
    ("mart_category_performance", build_category_performance),
    ("mart_region_performance", build_region_performance),
    ("mart_product_performance", build_product_performance),
    ("mart_channel_performance", build_channel_performance),
    ("mart_discount_impact", build_discount_impact),
    ("mart_payment_methods", build_payment_methods),
    ("mart_customer_rfm", build_customer_rfm),
    ("mart_customer_clv", build_customer_clv),
    ("mart_customer_retention", build_customer_retention),
    ("mart_sales_forecast", build_sales_forecast),
]


def refresh_marts() -> int:
    """Rebuild every analytics mart; returns the total number of rows written."""
    total = 0
    detail = {}
    for name, fn in MARTS:
        rows = fn()
        detail[name] = rows
        total += rows
        log.info(f"mart refreshed: {name}", extra={"stage": "analytics", "records": rows})
    meta = {
        "refreshed_at": datetime.utcnow().isoformat() + "Z",
        "marts": detail,
        "total_rows": total,
    }
    from etl.config import STAGING_DIR
    (STAGING_DIR / "analytics_manifest.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8")
    return total


def mart_counts() -> dict[str, int]:
    engine = get_engine()
    out: dict[str, int] = {}
    for name, _ in MARTS:
        try:
            out[name] = int(_q(engine, f"SELECT COUNT(*) FROM {name}") or 0)
        except Exception:
            out[name] = -1
    return out


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps({"rows": refresh_marts(), "marts": mart_counts()}, indent=2))
