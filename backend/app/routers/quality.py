"""GET /api/data-quality - DQ score, check results, history and quarantine."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from backend.app.db import one, rows, scalar
from backend.app.schemas import DataQualityResponse
from etl.transform.quality import latest_quality_summary

router = APIRouter(prefix="/api", tags=["data-quality"])


def _pages(total: int, size: int) -> int:
    return max(1, -(-total // size)) if total else 0


@router.get("/data-quality", response_model=DataQualityResponse,
            summary="Data quality score, every check, history and quarantine detail")
def data_quality(
    run_id: int | None = Query(None, ge=1, description="Inspect a specific run"),
    page: int = Query(1, ge=1, description="Quarantine sample page"),
    page_size: int = Query(20, ge=1, le=200),
    reason: str | None = Query(None, max_length=120),
) -> DataQualityResponse:
    summary = latest_quality_summary()

    if run_id:
        target_run = run_id
    else:
        target_run = scalar("SELECT MAX(run_id) FROM data_quality_results")
    target_run = int(target_run) if target_run else None

    checks = rows(
        "SELECT check_name, entity, status, metric, threshold, rows_failed, "
        "       message, created_at FROM data_quality_results "
        "WHERE run_id = :r ORDER BY status = 'pass', check_name",
        {"r": target_run},
    ) if target_run else []

    history = rows(
        "SELECT run_id, COUNT(*) AS checks, "
        "       SUM(CASE WHEN status = 'pass' THEN 1 ELSE 0 END) AS passed, "
        "       SUM(CASE WHEN status IN ('fail', 'error') THEN 1 ELSE 0 END) AS failed, "
        "       SUM(rows_failed) AS rows_failed, MAX(created_at) AS evaluated_at "
        "FROM data_quality_results GROUP BY run_id ORDER BY run_id DESC LIMIT 20"
    )

    total_q = int(scalar("SELECT COUNT(*) FROM quarantine") or 0)
    where, params = ["1 = 1"], {}
    if reason:
        where.append("reason = :reason")
        params["reason"] = reason
    if run_id:
        where.append("run_id = :run_id")
        params["run_id"] = run_id
    clause = " AND ".join(where)
    filtered = int(scalar(f"SELECT COUNT(*) FROM quarantine WHERE {clause}", params) or 0)
    sample = rows(
        f"SELECT id, run_id, source, entity, record_id, reason, severity, "
        f"       substr(payload, 1, 400) AS payload_preview, created_at "
        f"FROM quarantine WHERE {clause} ORDER BY id DESC LIMIT :limit OFFSET :offset",
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    )
    reasons = rows(
        "SELECT reason, entity, severity, COUNT(*) AS records, "
        "       MIN(created_at) AS first_seen, MAX(created_at) AS last_seen "
        "FROM quarantine GROUP BY reason, entity, severity "
        "ORDER BY records DESC"
    )

    return DataQualityResponse(
        score=summary.get("score"),
        summary={
            "checks_total": summary.get("checks_total"),
            "checks_passed": summary.get("checks_passed"),
            "checks_failed": summary.get("checks_failed"),
            "checks_warned": summary.get("checks_warned"),
            "evaluated_run": target_run,
            "quarantined_total": total_q,
            "quarantined_filtered": filtered,
            "enforced": "error-severity rows are quarantined and never reach the "
                        "warehouse; warning-severity rows are kept and recorded",
            "scoring": "score = (0.6 + 0.4 x pass_rate) x 100",
        },
        checks=checks,
        history=history,
        quarantine={
            "total": total_q, "filtered": filtered, "page": page,
            "page_size": page_size, "pages": _pages(filtered, page_size),
            "sample": sample, "filter_reason": reason, "filter_run_id": run_id,
        },
        quarantine_reasons=reasons,
    )


@router.get("/data-quality/checks", summary="Catalogue of implemented data quality checks")
def check_catalogue() -> dict:
    from etl.transform import quality

    names = [n for n in dir(quality) if n.startswith("check_") or n.startswith("no_")]
    latest = rows(
        "SELECT check_name, entity, status, rows_failed, message, created_at "
        "FROM data_quality_results WHERE id IN "
        "(SELECT MAX(id) FROM data_quality_results GROUP BY check_name) "
        "ORDER BY check_name"
    )
    return {
        "implemented_checks": len(latest) or len(names),
        "checks": latest,
        "categories": {
            "completeness": ["dim_customer_not_empty", "fresh_ingestion"],
            "uniqueness": ["no_duplicate_orders", "customer_scd2_single_current",
                           "product_scd2_single_current"],
            "referential_integrity": ["no_orphan_order_customers", "no_orphan_order_items",
                                      "no_orphan_item_products", "no_orphan_payments",
                                      "no_orphan_shipments", "no_orphan_returns"],
            "validity": ["orders_have_valid_dates", "no_negative_prices",
                         "payment_amounts_positive", "returns_positive_quantity"],
            "accuracy": ["order_totals_reconcile"],
        },
        "generated_at": datetime.utcnow().isoformat(),
    }
