"""Automated business reporting.

Generates the daily and weekly business reports after every pipeline run and
persists them three ways:

* ``data/reports/<report_id>.json``  - machine readable payload (API/report page)
* ``data/reports/<report_id>.md``    - Markdown for email / git history
* ``data/reports/<report_id>.html``  - self-contained HTML for the browser

Metadata lands in the ``reports`` warehouse table so the API can list history.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import text

from etl.config import REPORT_DIR
from etl.db import get_engine
from etl.logging_config import get_logger

log = get_logger("etl.reporting")


# --------------------------------------------------------------------- helpers
def _read(sql: str, params: dict | None = None) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def _scalar(engine, sql: str, params: dict | None = None):
    with engine.connect() as conn:
        return conn.execute(text(sql), params or {}).scalar()


def _num(v):
    if v is None:
        return 0.0
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


def _window_metrics(start: date, end: date) -> dict:
    """Aggregate the headline KPIs for an inclusive date window."""
    engine = get_engine()
    p = {"start": start.isoformat(), "end": end.isoformat()}
    row = _read("""
        SELECT COUNT(DISTINCT f.order_id)      AS orders,
               COUNT(DISTINCT f.customer_key)  AS customers,
               SUM(f.total_amount)             AS revenue,
               SUM(f.discount_amount)          AS discounts,
               SUM(f.item_count)               AS units
        FROM fact_orders f JOIN dim_date d ON f.date_key = d.date_key
        WHERE d.full_date BETWEEN :start AND :end AND f.status <> 'cancelled'
    """, p)

    pay = _read("""
        SELECT COUNT(*) AS attempts,
               SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes,
               SUM(CASE WHEN status = 'success' THEN amount ELSE 0 END) AS settled
        FROM fact_payments p JOIN dim_date d ON p.date_key = d.date_key
        WHERE d.full_date BETWEEN :start AND :end
    """, p)

    ret = _read("""
        SELECT COUNT(*) AS returns, SUM(refund_amount) AS refunds
        FROM fact_returns r JOIN dim_date d ON r.date_key = d.date_key
        WHERE d.full_date BETWEEN :start AND :end
    """, p)

    first_time = _scalar(engine, """
        SELECT COUNT(*) FROM (
            SELECT f.customer_key, MIN(d.full_date) AS first_day
            FROM fact_orders f JOIN dim_date d ON f.date_key = d.date_key
            WHERE f.status <> 'cancelled'
            GROUP BY f.customer_key
        ) t WHERE t.first_day BETWEEN :start AND :end
    """, p) or 0

    orders = int(row["orders"].iloc[0] or 0) if not row.empty else 0
    customers = int(row["customers"].iloc[0] or 0) if not row.empty else 0
    revenue = _num(row["revenue"].iloc[0] if not row.empty else 0)
    attempts = int(pay["attempts"].iloc[0] or 0) if not pay.empty else 0
    successes = int(pay["successes"].iloc[0] or 0) if not pay.empty else 0
    new_customers = int(first_time or 0)

    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "orders": orders,
        "revenue": revenue,
        "aov": round(revenue / orders, 2) if orders else 0.0,
        "units": int(row["units"].iloc[0] or 0) if not row.empty else 0,
        "discounts": _num(row["discounts"].iloc[0] if not row.empty else 0),
        "active_customers": customers,
        "new_customers": new_customers,
        "returning_customers": max(customers - new_customers, 0),
        "payments_attempted": attempts,
        "payment_success_rate_pct": round(successes / attempts * 100, 2) if attempts else 0.0,
        "settled_amount": _num(pay["settled"].iloc[0] if not pay.empty else 0),
        "returns": int(ret["returns"].iloc[0] or 0) if not ret.empty else 0,
        "refund_amount": _num(ret["refunds"].iloc[0] if not ret.empty else 0),
        "return_rate_pct": round((int(ret["returns"].iloc[0] or 0) / orders * 100), 2) if orders else 0.0,
    }


def _top_lists(start: date, end: date, limit: int = 5) -> dict:
    p = {"start": start.isoformat(), "end": end.isoformat(), "limit": limit}
    products = _read("""
        SELECT p.product_name, p.category, SUM(i.line_total) AS revenue,
               SUM(i.quantity) AS units
        FROM fact_order_items i
        JOIN dim_product p ON i.product_key = p.product_key
        JOIN fact_orders f ON i.order_key = f.order_key
        JOIN dim_date d ON f.date_key = d.date_key
        WHERE d.full_date BETWEEN :start AND :end
        GROUP BY p.product_name, p.category
        ORDER BY revenue DESC LIMIT :limit
    """, p)
    cats = _read("""
        SELECT p.category, SUM(i.line_total) AS revenue
        FROM fact_order_items i
        JOIN dim_product p ON i.product_key = p.product_key
        JOIN fact_orders f ON i.order_key = f.order_key
        JOIN dim_date d ON f.date_key = d.date_key
        WHERE d.full_date BETWEEN :start AND :end
        GROUP BY p.category ORDER BY revenue DESC LIMIT :limit
    """, p)
    regions = _read("""
        SELECT c.region, SUM(f.total_amount) AS revenue
        FROM fact_orders f
        JOIN dim_customer c ON f.customer_key = c.customer_key
        JOIN dim_date d ON f.date_key = d.date_key
        WHERE d.full_date BETWEEN :start AND :end
        GROUP BY c.region ORDER BY revenue DESC LIMIT :limit
    """, p)
    for df in (products, cats, regions):
        if not df.empty and "revenue" in df.columns:
            df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").round(2)
    return {
        "top_products": products.to_dict(orient="records"),
        "top_categories": cats.to_dict(orient="records"),
        "top_regions": regions.to_dict(orient="records"),
    }


def _growth(current: dict, previous: dict) -> dict:
    out = {}
    for key in ("revenue", "orders", "aov"):
        c, p = current.get(key, 0) or 0, previous.get(key, 0) or 0
        out[f"{key}_change_pct"] = round((c - p) / p * 100, 2) if p else None
    return out


# -------------------------------------------------------------------- renderers
def _markdown(report: dict) -> str:
    m = report["metrics"]
    prev = report.get("comparison", {})
    lines = [
        f"# {report['title']}",
        "",
        f"**Period:** {m['period_start']} to {m['period_end']}  ",
        f"**Generated:** {report['generated_at']}  ",
        f"**Pipeline run:** {report.get('run_id')}",
        "",
        "## Headline KPIs",
        "",
        "| Metric | Value | Previous period | Change |",
        "|---|---|---|---|",
        f"| Revenue | ${m['revenue']:,.2f} | ${prev.get('previous_revenue', 0):,.2f} | "
        f"{_fmt_pct(report['comparison'].get('revenue_change_pct'))} |",
        f"| Orders | {m['orders']:,} | {prev.get('previous_orders', 0):,} | "
        f"{_fmt_pct(report['comparison'].get('orders_change_pct'))} |",
        f"| Average order value | ${m['aov']:,.2f} | ${prev.get('previous_aov', 0):,.2f} | "
        f"{_fmt_pct(report['comparison'].get('aov_change_pct'))} |",
        f"| Active customers | {m['active_customers']:,} | - | - |",
        f"| New customers | {m['new_customers']:,} | - | - |",
        f"| Payment success rate | {m['payment_success_rate_pct']}% | - | - |",
        f"| Return rate | {m['return_rate_pct']}% | - | - |",
        "",
        "## Top products",
        "",
    ]
    for p in report["highlights"]["top_products"]:
        lines.append(f"- **{p['product_name']}** ({p['category']}) - ${p['revenue']:,.2f}")
    lines += ["", "## Top categories", ""]
    for c in report["highlights"]["top_categories"]:
        lines.append(f"- {c['category']} - ${c['revenue']:,.2f}")
    lines += ["", "## Top regions", ""]
    for r in report["highlights"]["top_regions"]:
        lines.append(f"- {r['region']} - ${r['revenue']:,.2f}")
    if report.get("notes"):
        lines += ["", "## Notes", ""] + [f"- {n}" for n in report["notes"]]
    lines += ["", "---", "", "_Generated automatically by the Divakar Automated ETL Data "
                     "Engineering Project._"]
    return "\n".join(lines)


def _fmt_pct(v) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.2f}%"


def _html(report: dict) -> str:
    m = report["metrics"]
    c = report.get("comparison", {})
    prod_rows = "".join(
        f"<tr><td>{p['product_name']}</td><td>{p['category']}</td>"
        f"<td class='num'>${p['revenue']:,.2f}</td><td class='num'>{p['units']:,}</td></tr>"
        for p in report["highlights"]["top_products"])
    cat_rows = "".join(
        f"<tr><td>{x['category']}</td><td class='num'>${x['revenue']:,.2f}</td></tr>"
        for x in report["highlights"]["top_categories"])
    reg_rows = "".join(
        f"<tr><td>{x['region']}</td><td class='num'>${x['revenue']:,.2f}</td></tr>"
        for x in report["highlights"]["top_regions"])
    notes = "".join(f"<li>{n}</li>" for n in report.get("notes", [])) or "<li>None</li>"

    def card(label, value, change=None):
        delta = ""
        if change is not None:
            cls = "up" if change >= 0 else "down"
            delta = f"<span class='{cls}'>{change:+.2f}%</span>"
        return (f"<div class='card'><div class='label'>{label}</div>"
                f"<div class='value'>{value}</div>{delta}</div>")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{report['title']}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;
       background:#f6f7fb;color:#1c2333;}}
 .wrap{{max-width:960px;margin:0 auto;padding:32px 20px 64px;}}
 h1{{font-size:26px;margin:0 0 4px;}}
 .sub{{color:#5c6780;font-size:13px;margin-bottom:24px;}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;
        margin-bottom:28px;}}
 .card{{background:#fff;border:1px solid #e4e8f0;border-radius:10px;padding:16px;}}
 .label{{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#6b7691;}}
 .value{{font-size:22px;font-weight:600;margin-top:6px;}}
 .up{{color:#0f9d58;font-size:12px;}} .down{{color:#d93025;font-size:12px;}}
 table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e4e8f0;
        border-radius:10px;overflow:hidden;margin-bottom:24px;font-size:13px;}}
 th{{background:#eef1f7;text-align:left;padding:10px 12px;font-size:11px;
     text-transform:uppercase;letter-spacing:.05em;color:#4a5470;}}
 td{{padding:9px 12px;border-top:1px solid #eef1f7;}}
 .num{{text-align:right;font-variant-numeric:tabular-nums;}}
 h2{{font-size:16px;margin:28px 0 10px;}}
 .foot{{color:#8a93a8;font-size:11px;margin-top:32px;}}
</style></head><body><div class="wrap">
<h1>{report['title']}</h1>
<div class="sub">Period {m['period_start']} &rarr; {m['period_end']} &middot;
 generated {report['generated_at']} &middot; run #{report.get('run_id')}</div>
<div class="grid">
 {card('Revenue', f"${m['revenue']:,.2f}", c.get('revenue_change_pct'))}
 {card('Orders', f"{m['orders']:,}", c.get('orders_change_pct'))}
 {card('Avg order value', f"${m['aov']:,.2f}", c.get('aov_change_pct'))}
 {card('Active customers', f"{m['active_customers']:,}")}
 {card('New customers', f"{m['new_customers']:,}")}
 {card('Payment success', f"{m['payment_success_rate_pct']}%")}
 {card('Return rate', f"{m['return_rate_pct']}%")}
</div>
<h2>Top products</h2>
<table><thead><tr><th>Product</th><th>Category</th><th class="num">Revenue</th>
<th class="num">Units</th></tr></thead><tbody>{prod_rows}</tbody></table>
<h2>Top categories</h2>
<table><thead><tr><th>Category</th><th class="num">Revenue</th></tr></thead>
<tbody>{cat_rows}</tbody></table>
<h2>Top regions</h2>
<table><thead><tr><th>Region</th><th class="num">Revenue</th></tr></thead>
<tbody>{reg_rows}</tbody></table>
<h2>Notes</h2><ul>{notes}</ul>
<div class="foot">Generated automatically by the Divakar Automated ETL Data Engineering Project.
All figures are computed from warehouse fact tables.</div>
</div></body></html>"""


# ------------------------------------------------------------------ public API
def _persist(report: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rid = report["report_id"]
    (REPORT_DIR / f"{rid}.json").write_text(json.dumps(report, indent=2, default=str),
                                            encoding="utf-8")
    (REPORT_DIR / f"{rid}.md").write_text(_markdown(report), encoding="utf-8")
    (REPORT_DIR / f"{rid}.html").write_text(_html(report), encoding="utf-8")

    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM reports WHERE report_id = :rid"), {"rid": rid})
        conn.execute(text("""
            INSERT INTO reports (report_id, report_type, period_start, period_end,
                                 title, summary_json, file_path, generated_at)
            VALUES (:rid, :rtype, :ps, :pe, :title, :summary, :path, :gen)
        """), {
            "rid": rid, "rtype": report["report_type"],
            "ps": report["period_start"], "pe": report["period_end"],
            "title": report["title"], "summary": json.dumps(report["metrics"]),
            "path": str(REPORT_DIR / f"{rid}.html"), "gen": datetime.utcnow(),
        })


def build_daily_report(run_id: int | None = None, day: date | None = None) -> dict:
    if day is None:
        with get_engine().connect() as conn:
            day = conn.execute(text("SELECT MAX(full_date) FROM dim_date d "
                                    "JOIN fact_orders f ON f.date_key = d.date_key")).scalar()
        if day is None:
            raise RuntimeError("no warehouse data available for a daily report")
        day = pd.to_datetime(day).date() if not isinstance(day, date) else day

    metrics = _window_metrics(day, day)
    prev_day = day - timedelta(days=1)
    prev = _window_metrics(prev_day, prev_day)
    comparison = {"previous_revenue": prev["revenue"], "previous_orders": prev["orders"],
                  "previous_aov": prev["aov"]}
    comparison.update(_growth(metrics, prev))

    notes = []
    if metrics["orders"] == 0:
        notes.append("No orders recorded for this date.")
    if metrics["payment_success_rate_pct"] and metrics["payment_success_rate_pct"] < 90:
        notes.append(f"Payment success rate below 90% "
                     f"({metrics['payment_success_rate_pct']}%).")
    if metrics["return_rate_pct"] > 10:
        notes.append(f"Return rate above 10% ({metrics['return_rate_pct']}%).")

    report = {
        "report_id": f"daily-{day.isoformat()}",
        "report_type": "daily",
        "period_start": day.isoformat(),
        "period_end": day.isoformat(),
        "title": f"Daily Business Report - {day.isoformat()}",
        "run_id": run_id,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "metrics": metrics,
        "comparison": comparison,
        "highlights": _top_lists(day, day),
        "notes": notes,
    }
    _persist(report)
    return report


def build_weekly_report(run_id: int | None = None, end: date | None = None) -> dict:
    if end is None:
        with get_engine().connect() as conn:
            raw = conn.execute(text("SELECT MAX(full_date) FROM dim_date d "
                                    "JOIN fact_orders f ON f.date_key = d.date_key")).scalar()
        if raw is None:
            raise RuntimeError("no warehouse data available for a weekly report")
        end = pd.to_datetime(raw).date() if not isinstance(raw, date) else raw
    start = end - timedelta(days=6)
    prev_start, prev_end = start - timedelta(days=7), start - timedelta(days=1)

    metrics = _window_metrics(start, end)
    prev = _window_metrics(prev_start, prev_end)
    comparison = {"previous_revenue": prev["revenue"], "previous_orders": prev["orders"],
                  "previous_aov": prev["aov"]}
    comparison.update(_growth(metrics, prev))

    # best day inside the window
    daily = _read("""
        SELECT d.full_date, SUM(f.total_amount) AS revenue
        FROM fact_orders f JOIN dim_date d ON f.date_key = d.date_key
        WHERE d.full_date BETWEEN :s AND :e AND f.status <> 'cancelled'
        GROUP BY d.full_date ORDER BY revenue DESC LIMIT 1
    """, {"s": start.isoformat(), "e": end.isoformat()})
    notes = []
    if not daily.empty:
        notes.append(f"Best trading day: {daily['full_date'].iloc[0]} with "
                     f"${_num(daily['revenue'].iloc[0]):,.2f} revenue.")
    notes.append(f"Week-over-week revenue change "
                 f"{_fmt_pct(comparison.get('revenue_change_pct'))}.")

    report = {
        "report_id": f"weekly-{start.isoformat()}_{end.isoformat()}",
        "report_type": "weekly",
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "title": f"Weekly Business Report - {start.isoformat()} to {end.isoformat()}",
        "run_id": run_id,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "metrics": metrics,
        "comparison": comparison,
        "highlights": _top_lists(start, end, limit=8),
        "notes": notes,
    }
    _persist(report)
    return report


def generate_reports(run_id: int | None = None) -> dict:
    """Build the daily + weekly reports for the current warehouse state."""
    files: list[str] = []
    generated = 0
    errors: list[str] = []
    for builder, label in ((build_daily_report, "daily"), (build_weekly_report, "weekly")):
        try:
            rep = builder(run_id)
            generated += 1
            files += [str(REPORT_DIR / f"{rep['report_id']}.{ext}")
                      for ext in ("json", "md", "html")]
            log.info(f"{label} report generated", extra={"run_id": run_id,
                                                         "stage": "reporting"})
        except Exception as exc:  # keep the pipeline green if one report fails
            errors.append(f"{label}: {exc}")
            log.error(f"{label} report failed: {exc}", extra={"run_id": run_id})
    return {"reports_generated": generated, "files": files, "errors": errors}


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(generate_reports(), indent=2))
