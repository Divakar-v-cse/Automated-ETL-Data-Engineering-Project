"""GET /health - liveness probe plus a warehouse snapshot."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from backend.app.db import one, table_count
from backend.app.schemas import HealthResponse
from etl.config import APP_NAME, APP_VERSION
from etl.db import healthcheck

router = APIRouter(tags=["system"])

WAREHOUSE_TABLES = (
    "dim_customer", "dim_product", "dim_date", "dim_payment",
    "fact_orders", "fact_order_items", "fact_payments", "fact_shipments",
    "fact_returns",
)


@router.get("/health", response_model=HealthResponse, summary="Service and database health")
def health() -> HealthResponse:
    db = healthcheck()
    warehouse = {table: table_count(table) for table in WAREHOUSE_TABLES}
    latest = one(
        "SELECT run_id, dag_id, status, trigger, started_at, finished_at, "
        "       duration_seconds, records_loaded, quality_score "
        "FROM pipeline_runs ORDER BY run_id DESC LIMIT 1"
    )
    return HealthResponse(
        status="ok" if db.get("database") == "up" else "degraded",
        app=APP_NAME,
        version=APP_VERSION,
        database=db,
        warehouse=warehouse,
        latest_run=latest,
        generated_at=datetime.utcnow(),
    )
