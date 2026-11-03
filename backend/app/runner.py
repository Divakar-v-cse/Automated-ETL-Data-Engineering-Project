"""Background execution of ETL workflows for the API.

The API never runs a pipeline inline (a full run takes several minutes), so
``POST /api/pipeline/trigger`` starts a worker thread and returns the run id,
which the UI then polls through ``GET /api/pipeline/status``.

Only one run may be active at a time - exactly like Airflow's ``max_active_runs``.
"""
from __future__ import annotations

import threading
import traceback
from datetime import datetime, timezone
from typing import Any

from backend.app.db import one
from etl.logging_config import get_logger
from etl.pipeline import run_dag

log = get_logger("api.runner", log_file="api.log")


class RunBusy(RuntimeError):
    """Raised when a workflow is already running."""


_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"active": None, "last": None}


def active() -> dict | None:
    return _STATE["active"]


def last() -> dict | None:
    return _STATE["last"]


def _wait_for_run_row(started_after: datetime, dag_id: str, timeout: float = 5.0) -> int | None:
    """Poll briefly for the ledger row the pipeline creates as its first action."""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        row = one(
            "SELECT run_id FROM pipeline_runs WHERE dag_id = :d AND started_at >= :s "
            "ORDER BY run_id DESC LIMIT 1",
            {"d": dag_id, "s": started_after.replace(tzinfo=None).isoformat(sep=" ")},
        )
        if row:
            return int(row["run_id"])
        time.sleep(0.25)
    return None


def trigger(dag_id: str, incremental: bool = True, skip_reporting: bool = False,
            trigger_type: str = "manual") -> dict:
    """Start a DAG in a worker thread. Returns immediately with the run id."""
    with _LOCK:
        if _STATE["active"] is not None:
            raise RunBusy(
                f"run {_STATE['active'].get('run_id')} "
                f"({_STATE['active'].get('dag_id')}) is still in progress"
            )
        started_at = datetime.now(timezone.utc)
        job: dict[str, Any] = {
            "dag_id": dag_id, "incremental": incremental,
            "skip_reporting": skip_reporting, "trigger": trigger_type,
            "started_at": started_at.isoformat(), "run_id": None, "status": "starting",
        }
        _STATE["active"] = job

    def _work() -> None:
        try:
            result = run_dag(dag_id, trigger=trigger_type, incremental=incremental,
                             skip_reporting=skip_reporting)
            job.update(run_id=result.get("run_id"), status=result.get("status"),
                       finished_at=datetime.now(timezone.utc).isoformat(),
                       counters=result.get("counters"),
                       quality_score=result.get("quality_score"),
                       error=result.get("error"))
            log.info("dag complete", extra={"dag_id": dag_id,
                                            "run_id": result.get("run_id"),
                                            "status": result.get("status")})
        except Exception as exc:  # pragma: no cover - defensive
            job.update(status="failed", error=str(exc),
                       finished_at=datetime.now(timezone.utc).isoformat())
            log.error(f"dag crashed: {exc}\n{traceback.format_exc()}",
                      extra={"dag_id": dag_id})
        finally:
            with _LOCK:
                _STATE["last"] = job
                _STATE["active"] = None

    thread = threading.Thread(target=_work, name=f"etl-{dag_id}", daemon=True)
    thread.start()

    run_id = _wait_for_run_row(started_at, dag_id)
    with _LOCK:
        if _STATE["active"] is job:
            job["run_id"] = run_id
            job["status"] = "running" if run_id else "starting"
    return {"run_id": run_id, "dag_id": dag_id,
            "status": "running" if run_id else "starting",
            "started_at": started_at.isoformat()}


def coverage(start: str, end: str) -> list[dict]:
    """Per-day order coverage for a backfill window (evidence the range is loaded)."""
    from backend.app.db import rows

    return rows(
        "SELECT d.full_date AS day, COUNT(*) AS orders, "
        "       SUM(f.total_amount) AS revenue "
        "FROM fact_orders f JOIN dim_date d ON d.date_key = f.date_key "
        "WHERE d.full_date BETWEEN :a AND :b "
        "GROUP BY d.full_date ORDER BY d.full_date",
        {"a": start, "b": end},
    )
