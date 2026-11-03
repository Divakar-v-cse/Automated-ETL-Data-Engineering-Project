"""Pipeline monitoring, execution history, triggering and backfills."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from backend.app import runner
from backend.app.db import one, rows, scalar
from backend.app.schemas import (BackfillRequest, BackfillResponse,
                                 PipelineHistoryResponse, PipelineStatusResponse,
                                 TriggerAcceptedResponse, TriggerRequest)
from etl.config import QUALITY_SCORE_THRESHOLD
from etl.logging_config import get_logger

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
log = get_logger("api.pipeline", log_file="api.log")

FACT_TABLES = ("fact_orders", "fact_order_items", "fact_payments",
               "fact_shipments", "fact_returns")

RUN_COLUMNS = (
    "run_id, dag_id, status, trigger, started_at, finished_at, duration_seconds, "
    "records_extracted, records_transformed, records_loaded, records_rejected, "
    "quality_score, error"
)


def _pages(total: int, size: int) -> int:
    return max(1, -(-total // size)) if total else 0


def _age_minutes(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        value = datetime.fromisoformat(str(stamp).replace("Z", ""))
    except ValueError:
        return None
    return round((datetime.utcnow() - value).total_seconds() / 60, 1)


@router.get("/status", response_model=PipelineStatusResponse,
            summary="Live pipeline status, stage timings, freshness and success rate")
def status() -> PipelineStatusResponse:
    latest = one(f"SELECT {RUN_COLUMNS}, log FROM pipeline_runs "
                 f"ORDER BY run_id DESC LIMIT 1")
    active_job = runner.active()

    tasks = []
    if latest:
        tasks = rows(
            "SELECT task_id, task_name, status, attempt, started_at, finished_at, "
            "       duration_seconds, message FROM pipeline_tasks "
            "WHERE run_id = :r ORDER BY task_id", {"r": latest["run_id"]},
        )

    window = rows("SELECT status, duration_seconds FROM pipeline_runs "
                  "ORDER BY run_id DESC LIMIT 20")
    # Success rate must only consider terminal executions: an in-flight run is not
    # a failure, so `running`/`queued` rows are excluded from the denominator.
    terminal = [r for r in window if r["status"] in ("success", "failed")]
    running = len(window) - len(terminal)
    ok = sum(1 for r in terminal if r["status"] == "success")
    durations = [r["duration_seconds"] for r in terminal
                 if r["status"] == "success" and r["duration_seconds"]]
    last_success = one(f"SELECT {RUN_COLUMNS} FROM pipeline_runs "
                       f"WHERE status = 'success' ORDER BY run_id DESC LIMIT 1")
    failed_tasks = rows(
        "SELECT t.task_id, t.run_id, t.task_name, t.status, t.attempt, "
        "       t.finished_at, t.message FROM pipeline_tasks t "
        "WHERE t.status = 'failed' ORDER BY t.task_id DESC LIMIT 10"
    )

    freshness = []
    for table in FACT_TABLES:
        stamp = scalar(f"SELECT MAX(ingested_at) FROM {table}")
        freshness.append({
            "table": table,
            "last_ingested_at": stamp,
            "age_minutes": _age_minutes(stamp),
            "rows": int(scalar(f"SELECT COUNT(*) FROM {table}") or 0),
        })

    return PipelineStatusResponse(
        status=(active_job or {}).get("status") or (latest or {}).get("status", "never_run"),
        active_run=active_job,
        latest_run=latest,
        stages=tasks,
        health={
            "runs_considered": len(terminal),
            "successful_runs": ok,
            "failed_runs": len(terminal) - ok,
            "in_flight_runs": running,
            "avg_duration_seconds": round(sum(durations) / len(durations), 1) if durations else None,
            "last_successful_execution": last_success,
            "last_successful_finished_at": (last_success or {}).get("finished_at"),
            "failed_tasks": failed_tasks,
            "quality_threshold": QUALITY_SCORE_THRESHOLD,
            "scheduler": "in-repo Airflow-compatible runner "
                         "(see docs/LIMITATIONS.md)",
        },
        freshness=freshness,
        watermarks=rows("SELECT source, last_value, last_run_at FROM etl_watermarks "
                        "ORDER BY source"),
        success_rate_pct=round(ok / len(terminal) * 100, 2) if terminal else None,
    )


@router.get("/history", response_model=PipelineHistoryResponse,
            summary="Paginated execution history, optionally with task detail")
def history(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: str | None = Query(None, pattern="^(running|success|failed)$"),
    dag_id: str | None = Query(None, max_length=120),
    run_id: int | None = Query(None, ge=1, description="Include tasks for this run"),
) -> PipelineHistoryResponse:
    where, params = ["1 = 1"], {}
    if status:
        where.append("status = :status")
        params["status"] = status
    if dag_id:
        where.append("dag_id = :dag_id")
        params["dag_id"] = dag_id
    clause = " AND ".join(where)
    total = int(scalar(f"SELECT COUNT(*) FROM pipeline_runs WHERE {clause}", params) or 0)
    items = rows(
        f"SELECT {RUN_COLUMNS} FROM pipeline_runs WHERE {clause} "
        f"ORDER BY run_id DESC LIMIT :limit OFFSET :offset",
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    )
    tasks = []
    if run_id:
        tasks = rows(
            "SELECT task_id, task_name, status, attempt, started_at, finished_at, "
            "       duration_seconds, message, log FROM pipeline_tasks "
            "WHERE run_id = :r ORDER BY task_id", {"r": run_id},
        )
    elif items:
        tasks = rows(
            "SELECT task_id, task_name, status, attempt, started_at, finished_at, "
            "       duration_seconds, message FROM pipeline_tasks "
            "WHERE run_id = :r ORDER BY task_id", {"r": items[0]["run_id"]},
        )
    return PipelineHistoryResponse(items=items, page=page, page_size=page_size,
                                   total=total, pages=_pages(total, page_size),
                                   tasks=tasks)


@router.post("/trigger", response_model=TriggerAcceptedResponse, status_code=202,
             summary="Trigger an ETL workflow (async by default)")
def trigger(payload: TriggerRequest) -> TriggerAcceptedResponse:
    if runner.active():
        active = runner.active()
        raise HTTPException(
            status_code=409,
            detail=f"run {active.get('run_id')} ({active.get('dag_id')}) is already "
                   f"in progress; wait for it to finish",
        )
    if payload.mode == "sync":
        from etl.pipeline import run_dag
        result = run_dag(payload.dag_id, trigger="manual",
                         incremental=payload.incremental,
                         skip_reporting=payload.skip_reporting)
        return TriggerAcceptedResponse(
            run_id=result.get("run_id"), dag_id=payload.dag_id,
            status=result.get("status", "unknown"), mode="sync",
            started_at=datetime.utcnow(),
            message=f"completed with status {result.get('status')}",
        )

    started = datetime.utcnow()
    try:
        info = runner.trigger(payload.dag_id, payload.incremental,
                              payload.skip_reporting, trigger_type="manual")
    except runner.RunBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log.info("manual trigger accepted", extra={"dag_id": payload.dag_id,
                                               "run_id": info.get("run_id")})
    return TriggerAcceptedResponse(
        run_id=info.get("run_id"), dag_id=payload.dag_id, status=info.get("status"),
        mode="async", started_at=started,
        message="workflow started in a background worker; poll /api/pipeline/status",
    )


@router.post("/backfill", response_model=BackfillResponse, status_code=202,
             summary="Replay a historical date window")
def backfill(payload: BackfillRequest) -> BackfillResponse:
    if runner.active():
        active = runner.active()
        raise HTTPException(status_code=409,
                            detail=f"run {active.get('run_id')} is in progress")
    start = payload.start_date.isoformat()
    end = payload.end_date.isoformat()
    partitions = (payload.end_date - payload.start_date).days + 1

    try:
        info = runner.trigger(payload.dag_id, incremental=payload.incremental,
                              skip_reporting=False, trigger_type="backfill")
    except runner.RunBusy as exc:  # pragma: no cover - guarded above
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    covered = runner.coverage(start, end)
    missing = partitions - len(covered)
    return BackfillResponse(
        dag_id=payload.dag_id, start_date=payload.start_date,
        end_date=payload.end_date, partitions=partitions,
        run_id=info.get("run_id"), status=info.get("status", "running"),
        coverage=covered,
        message=(f"backfill of {partitions} partition(s) started; "
                 f"{len(covered)} day(s) already hold data, {max(missing, 0)} were empty. "
                 f"Loads are idempotent upserts, so replay is safe to repeat."),
    )


@router.get("/watermarks", summary="Incremental extraction watermarks")
def watermarks() -> dict:
    return {
        "watermarks": rows("SELECT source, last_value, last_run_at FROM etl_watermarks "
                           "ORDER BY source"),
        "incremental_sources": ["json:orders", "api:payments", "db:shipments"],
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/schedule", summary="Declared DAG schedule and stage graph")
def schedule() -> dict:
    from etl.pipeline import DAG_STAGES
    return {
        "dags": [
            {"dag_id": "daily_etl_pipeline", "schedule": "0 2 * * *",
             "stages": DAG_STAGES["daily_etl_pipeline"],
             "description": "Full daily extract -> validate -> load -> DQ -> marts -> reports"},
            {"dag_id": "incremental_ingestion_pipeline", "schedule": "0 */4 * * *",
             "stages": DAG_STAGES["incremental_ingestion_pipeline"],
             "description": "Watermark-based incremental ingestion"},
            {"dag_id": "data_quality_pipeline", "schedule": "30 2 * * *",
             "stages": DAG_STAGES["data_quality_pipeline"],
             "description": "Warehouse validation + DQ report"},
            {"dag_id": "analytics_pipeline", "schedule": "45 2 * * *",
             "stages": DAG_STAGES["analytics_pipeline"],
             "description": "Sales, revenue, retention and product marts"},
            {"dag_id": "reporting_pipeline", "schedule": "0 3 * * 1",
             "stages": DAG_STAGES["reporting_pipeline"],
             "description": "Daily and weekly business reports"},
        ],
        "retries": 2,
        "retry_backoff": "linear (1s x attempt)",
        "next_window": (date.today() + timedelta(days=1)).isoformat(),
    }
