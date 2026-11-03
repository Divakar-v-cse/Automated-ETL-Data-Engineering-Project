"""ETL pipeline orchestration.

Stage contract
--------------
Each stage is a pure function that reads/writes artefacts under
``data/staging`` so it can run inside an Airflow worker, a Celery queue or the
local runner without sharing process memory (the Airflow equivalent of XCom +
object storage).

    extract -> validate -> load -> quality -> analytics -> reporting
"""
from __future__ import annotations

import json
import pickle
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from sqlalchemy import text

from etl import schema as S
from etl.config import PIPELINE_RETRIES, PIPELINE_RETRY_DELAY, QUALITY_SCORE_THRESHOLD, STAGING_DIR
from etl.db import get_engine
from etl.extract import (ensure_source_table, extract_api, extract_csv, extract_db,
                         extract_jsonl)
from etl.extract.base import set_watermark
from etl.load import loader
from etl.logging_config import get_logger
from etl.transform import validators
from etl.transform.quality import run_quality_checks
from etl.transform.transformers import (enrich_items, enrich_orders, enrich_payments,
                                        enrich_returns, enrich_shipments)

log = get_logger("etl.pipeline")
ENTITIES = ["customers", "products", "orders", "order_items", "payments", "shipments", "returns"]


def warehouse_order_ids() -> set[str]:
    """Order IDs already persisted in the warehouse.

    Referential integrity for child entities (items, payments, shipments,
    returns) must be judged against the whole warehouse, not just the current
    batch. An incremental window only extracts the orders that changed, so a
    batch-only reference set would flag every untouched parent as missing and
    quarantine the entire child feed (observed: 423k orphan rejections).
    """
    try:
        with get_engine().connect() as conn:
            return {str(r[0]) for r in conn.execute(text("SELECT order_id FROM fact_orders"))}
    except Exception:  # first run, or table not created yet
        return set()


# ------------------------------------------------------------------ run ledger
def start_run(dag_id: str, trigger: str = "manual", mode: str = "full") -> int:
    with get_engine().begin() as conn:
        result = conn.execute(S.pipeline_runs.insert().values(
            dag_id=dag_id, status="running", trigger=trigger,
            started_at=datetime.utcnow(), records_extracted=0, records_transformed=0,
            records_loaded=0, records_rejected=0, log="[]",
        ))
        return int(result.inserted_primary_key[0])


def finish_run(run_id: int, status: str, counters: dict, log_lines: list[str],
               quality_score: float | None = None, error: str | None = None) -> None:
    with get_engine().begin() as conn:
        row = conn.execute(text("SELECT started_at FROM pipeline_runs WHERE run_id = :r"),
                           {"r": run_id}).first()
        started = row[0] if row else datetime.utcnow()
        if isinstance(started, str):
            started = datetime.fromisoformat(started)
        duration = round((datetime.utcnow() - started).total_seconds(), 2)
        conn.execute(S.pipeline_runs.update().where(S.pipeline_runs.c.run_id == run_id).values(
            status=status, finished_at=datetime.utcnow(), duration_seconds=duration,
            records_extracted=counters.get("extracted", 0),
            records_transformed=counters.get("transformed", 0),
            records_loaded=counters.get("loaded", 0),
            records_rejected=counters.get("rejected", 0),
            quality_score=quality_score, error=error,
            log=json.dumps(log_lines[-400:], default=str),
        ))


def run_task(run_id: int, name: str, fn: Callable[[], Any],
             retries: int = PIPELINE_RETRIES) -> Any:
    """Execute one task with retries; every attempt is logged to pipeline_tasks."""
    last_exc: Exception | None = None
    for attempt in range(1, retries + 2):
        started = datetime.utcnow()
        task_id = None
        with get_engine().begin() as conn:
            res = conn.execute(S.pipeline_tasks.insert().values(
                run_id=run_id, task_name=name, status="running", attempt=attempt,
                started_at=started))
            task_id = int(res.inserted_primary_key[0])
        try:
            result = fn()
            elapsed = round((datetime.utcnow() - started).total_seconds(), 3)
            msg = result if isinstance(result, str) else json.dumps(
                result, default=str)[:2000] if isinstance(result, dict) else "ok"
            with get_engine().begin() as conn:
                conn.execute(S.pipeline_tasks.update()
                             .where(S.pipeline_tasks.c.task_id == task_id)
                             .values(status="success", finished_at=datetime.utcnow(),
                                     duration_seconds=elapsed, message=str(msg)[:2000]))
            log.info("task complete", extra={"run_id": run_id, "task": name,
                                             "duration_s": elapsed})
            return result
        except Exception as exc:
            elapsed = round((datetime.utcnow() - started).total_seconds(), 3)
            last_exc = exc
            with get_engine().begin() as conn:
                conn.execute(S.pipeline_tasks.update()
                             .where(S.pipeline_tasks.c.task_id == task_id)
                             .values(status="failed", finished_at=datetime.utcnow(),
                                     duration_seconds=elapsed, message=str(exc)[:2000],
                                     log=f"attempt {attempt} failed: {exc}"))
            log.error(f"task failed: {exc}", extra={"run_id": run_id, "task": name})
            if attempt <= retries:
                time.sleep(PIPELINE_RETRY_DELAY * attempt)
    raise RuntimeError(f"Task '{name}' failed after {retries + 1} attempts: {last_exc}")


# --------------------------------------------------------------- stage plumbing
def _path(kind: str, entity: str) -> Path:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    return STAGING_DIR / f"{kind}_{entity}.pkl"


def _save(kind: str, entity: str, obj: Any) -> None:
    with open(_path(kind, entity), "wb") as fh:
        pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)


def _load(kind: str, entity: str) -> Any:
    with open(_path(kind, entity), "rb") as fh:
        return pickle.load(fh)


def stage_extract(run_id: int, incremental: bool = False) -> dict:
    """Pull every upstream source and persist raw frames for the next stage."""
    ensure_source_table()
    results = {
        "customers": extract_csv("customers", "customers.csv", incremental=False),
        "products": extract_csv("products", "products.csv", incremental=False),
        "orders": extract_jsonl("orders", "orders.jsonl", incremental=incremental),
        "order_items": extract_csv("order_items", "order_items.csv", incremental=False),
        "payments": extract_api("payments"),
        "shipments": extract_db("shipments", incremental=False),
        "returns": extract_csv("returns", "returns.csv", incremental=False),
    }
    # SCD2 second snapshot: applied as a change feed (only changed rows arrive)
    updates = {
        "customers": extract_csv("customers_updates", "customers_updates.csv"),
        "products": extract_csv("products_updates", "products_updates.csv"),
    }

    manifest = {}
    for entity, res in results.items():
        _save("raw", entity, res.frame)
        manifest[entity] = {"source": res.source, "records": res.records,
                            "duration_s": res.duration_seconds, "meta": res.meta}
    for entity, res in updates.items():
        _save("feed", entity, res.frame)
        manifest[f"{entity}_feed"] = {"source": res.source, "records": res.records,
                                      "duration_s": res.duration_seconds, "meta": res.meta}

    total = sum(v["records"] for v in manifest.values())
    manifest["_total"] = total
    (STAGING_DIR / "extract_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return {"records": total, "sources": len(manifest) - 1}


def stage_validate(run_id: int) -> dict:
    """Clean + apply business rules; persist clean frames and rejection lists."""
    raw = {e: _load("raw", e) for e in ENTITIES}
    clean: dict[str, pd.DataFrame] = {}
    rejected: list[dict] = []
    warned: list[dict] = []
    stats: dict[str, dict] = {}

    def _consume(out) -> Any:
        """Collect rejections (blocked rows) and warnings (kept rows)."""
        rejected.extend(out.rejected)
        warned.extend(out.warnings)
        stats[out.entity] = out.stats
        return out.frame

    with get_engine().connect() as conn:
        known_customers = set(pd.read_sql(text("SELECT customer_id FROM dim_customer "
                                               "WHERE is_current IS TRUE"), conn)["customer_id"])
        known_products = set(pd.read_sql(text("SELECT product_id FROM dim_product "
                                               "WHERE is_current IS TRUE"), conn)["product_id"])
        # A change feed can only supersede history that already exists. On a
        # seeding run the dimension is empty, so the feed is deferred to the next
        # run; otherwise the changed attributes would land as version 1 and the
        # SCD2 timeline would be lost.
        seeded = {
            "customers": int(conn.execute(
                text("SELECT COUNT(*) FROM dim_customer")).scalar() or 0) > 0,
            "products": int(conn.execute(
                text("SELECT COUNT(*) FROM dim_product")).scalar() or 0) > 0,
        }

    # dimensions first: feed in the SCD2 change rows before validating facts
    for entity in ("customers", "products"):
        base = raw[entity]
        feed = _load("feed", entity)
        if seeded[entity]:
            combined = pd.concat([base, feed], ignore_index=True)
            # keep="last": the change feed row supersedes the base snapshot so the
            # loader sees a real attribute delta and writes SCD2 version n+1.
            out = getattr(validators, f"validate_{entity}")(combined, keep="last")
            deferred = 0
        else:
            out = getattr(validators, f"validate_{entity}")(base, keep="first")
            deferred = len(feed)
        clean[entity] = _consume(out)
        stats[entity]["change_feed_deferred"] = deferred
        if entity == "customers":
            known_customers |= set(clean["customers"]["customer_id"])
        else:
            known_products |= set(clean["products"]["product_id"])

    out = validators.validate_orders(raw["orders"], known_customers)
    clean["orders"] = enrich_orders(_consume(out))
    # batch orders + orders already in the warehouse = the valid reference set
    batch_orders = set(clean["orders"]["order_id"])
    order_ids = batch_orders | warehouse_order_ids()
    stats["orders"]["reference_set_size"] = len(order_ids)
    stats["orders"]["previously_loaded_orders"] = len(order_ids - batch_orders)

    out = validators.validate_order_items(raw["order_items"], order_ids, known_products)
    clean["order_items"] = _consume(out)

    out = validators.validate_payments(raw["payments"], order_ids)
    clean["payments"] = _consume(out)

    out = validators.validate_shipments(raw["shipments"], order_ids)
    clean["shipments"] = _consume(out)

    out = validators.validate_returns(raw["returns"], order_ids, known_products)
    clean["returns"] = _consume(out)

    for entity, frame in clean.items():
        _save("clean", entity, frame)
    with open(STAGING_DIR / "rejected.json", "w", encoding="utf-8") as fh:
        json.dump(rejected, fh, default=str)

    # warnings are retained rows: they never reach quarantine, but every finding
    # is preserved so the DQ report can explain the anomaly without losing volume.
    by_reason: dict[str, int] = {}
    for w in warned:
        by_reason[w["reason"]] = by_reason.get(w["reason"], 0) + 1
    warning_summary = {"total": len(warned), "by_reason": by_reason}
    (STAGING_DIR / "warnings.json").write_text(
        json.dumps({"summary": warning_summary, "rows": warned[:5000]},
                   indent=2, default=str), encoding="utf-8")

    total_clean = sum(len(f) for f in clean.values())
    return {"records": total_clean, "rejected": len(rejected), "warnings": len(warned),
            "warning_reasons": by_reason,
            "per_entity": {k: len(v) for k, v in clean.items()},
            "entity_stats": stats}


def stage_load(run_id: int) -> dict:
    """Staging tables -> SCD2 dimensions -> fact upserts, in one transaction each."""
    batch_id = run_id
    loader.load_dim_date()
    loader.load_dim_payment()

    clean = {e: _load("clean", e) for e in ENTITIES}
    for entity in ENTITIES:
        loader.load_staging(entity, clean[entity], batch_id)

    # SCD2 dimensions
    dim_stats = {
        "customers": loader.load_customers(clean["customers"]),
        "products": loader.load_products(clean["products"]),
    }

    with get_engine().connect() as conn:
        maps = loader._key_maps(conn)
        okeys = loader.order_key_map(conn)

    loaded = {}
    loaded["orders"] = loader.load_fact_orders(clean["orders"], maps)
    with get_engine().connect() as conn:
        okeys = loader.order_key_map(conn)
    items = enrich_items(clean["order_items"], clean["orders"], clean["products"])
    loaded["order_items"] = loader.load_fact_items(items, maps, okeys)
    payments = enrich_payments(clean["payments"], clean["orders"])
    loaded["payments"] = loader.load_fact_payments(payments, maps, okeys)
    shipments = enrich_shipments(clean["shipments"], clean["orders"])
    loaded["shipments"] = loader.load_fact_shipments(shipments, okeys)
    returns = enrich_returns(clean["returns"], clean["orders"], clean["products"])
    loaded["returns"] = loader.load_fact_returns(returns, maps, okeys)

    # persist quarantine rows for this run
    with open(STAGING_DIR / "rejected.json", encoding="utf-8") as fh:
        rejected = json.load(fh)
    loader.write_quarantine(run_id, rejected, source="multi-source")
    (STAGING_DIR / "load_result.json").write_text(
        json.dumps({"loaded": loaded, "dim_scd2": dim_stats}, indent=2), encoding="utf-8")

    return {"records": sum(loaded.values()), "per_entity": loaded, "scd2": dim_stats}


def stage_quality(run_id: int) -> dict:
    summary = run_quality_checks(run_id)
    (STAGING_DIR / "quality_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return {"records": summary["checks_total"], "score": summary["score"],
            "failed": summary["checks_failed"]}


def stage_analytics(run_id: int) -> dict:
    from etl.analytics import refresh_marts
    return {"records": refresh_marts(), "marts": "refreshed"}


def stage_reporting(run_id: int) -> dict:
    from etl.reporting import generate_reports
    out = generate_reports(run_id)
    return {"records": out["reports_generated"], "files": out["files"]}


STAGES = {
    "extract": stage_extract,
    "validate": stage_validate,
    "load": stage_load,
    "quality": stage_quality,
    "analytics": stage_analytics,
    "reporting": stage_reporting,
}

# DAG registry: every Airflow DAG in airflow/dags maps to a stage subset here, so
# the same code path serves the scheduler, the API trigger and the CLI.
DAG_STAGES: dict[str, list[str]] = {
    "daily_etl_pipeline": ["extract", "validate", "load", "quality", "analytics", "reporting"],
    "incremental_ingestion_pipeline": ["extract", "validate", "load", "quality"],
    "data_quality_pipeline": ["quality"],
    "analytics_pipeline": ["analytics"],
    "reporting_pipeline": ["reporting"],
}


def run_stages(dag_id: str, stages: list[str], trigger: str = "manual",
               incremental: bool = True) -> dict:
    """Run an arbitrary subset of the stage graph as one monitored pipeline run.

    This is the function the Airflow tasks, the CLI and ``POST /api/pipeline/trigger``
    all call, which keeps orchestration behaviour identical across entry points.
    """
    unknown = [s for s in stages if s not in STAGES]
    if unknown:
        raise ValueError(f"unknown stages: {unknown}")

    run_id = start_run(dag_id, trigger, "incremental" if incremental else "full")
    counters = {"extracted": 0, "transformed": 0, "loaded": 0, "rejected": 0}
    logs: list[str] = [f"[{datetime.utcnow().isoformat()}] run {run_id} started "
                       f"(dag={dag_id}, trigger={trigger}, incremental={incremental}, "
                       f"stages={stages})"]
    status, error, quality_score = "success", None, None

    try:
        for stage in stages:
            if stage == "extract":
                out = run_task(run_id, "extract_sources",
                               lambda: stage_extract(run_id, incremental))
                counters["extracted"] = out["records"]
                logs.append(f"extract: {out['records']} records from {out['sources']} sources")
            elif stage == "validate":
                out = run_task(run_id, "validate_and_transform", lambda: stage_validate(run_id))
                counters["transformed"] = out["records"]
                counters["rejected"] = out["rejected"]
                logs.append(f"validate: {out['records']} clean / {out['rejected']} quarantined "
                            f"/ {out.get('warnings', 0)} warnings")
            elif stage == "load":
                out = run_task(run_id, "load_warehouse", lambda: stage_load(run_id))
                counters["loaded"] = out["records"]
                logs.append(f"load: {out['records']} rows loaded")
            elif stage == "quality":
                out = run_task(run_id, "data_quality_checks", lambda: stage_quality(run_id))
                quality_score = out["score"]
                logs.append(f"quality: score={out['score']} failed_checks={out['failed']}")
                if out["score"] < QUALITY_SCORE_THRESHOLD:
                    logs.append(f"WARNING: quality score below threshold {QUALITY_SCORE_THRESHOLD}")
            elif stage == "analytics":
                out = run_task(run_id, "refresh_analytics_marts", lambda: stage_analytics(run_id))
                logs.append(f"analytics: {out['records']} mart rows refreshed")
            elif stage == "reporting":
                out = run_task(run_id, "generate_reports", lambda: stage_reporting(run_id))
                logs.append(f"reporting: {out['records']} reports generated")

        if "load" in stages:
            with get_engine().connect() as conn:
                max_ts = conn.execute(text("SELECT MAX(updated_at) FROM fact_orders")).scalar()
            if max_ts:
                set_watermark("json:orders", str(max_ts))

    except Exception as exc:
        status = "failed"
        error = str(exc)
        logs.append(f"FAILED: {exc}")
        log.error(str(exc), extra={"run_id": run_id, "dag_id": dag_id})

    finish_run(run_id, status, counters, logs, quality_score, error)
    return {"run_id": run_id, "dag_id": dag_id, "status": status, "counters": counters,
            "quality_score": quality_score, "error": error, "log": logs}


# ------------------------------------------------------------------- the runner
def run_pipeline(dag_id: str = "daily_etl_pipeline", trigger: str = "manual",
                 incremental: bool = True, skip_reporting: bool = False) -> dict:
    run_id = start_run(dag_id, trigger, "incremental" if incremental else "full")
    counters = {"extracted": 0, "transformed": 0, "loaded": 0, "rejected": 0}
    logs: list[str] = [f"[{datetime.utcnow().isoformat()}] run {run_id} started "
                       f"(dag={dag_id}, trigger={trigger}, incremental={incremental})"]
    status = "success"
    error = None
    quality_score = None

    try:
        out = run_task(run_id, "extract_sources", lambda: stage_extract(run_id, incremental))
        counters["extracted"] = out["records"]
        logs.append(f"extract: {out['records']} records from {out['sources']} sources")

        out = run_task(run_id, "validate_and_transform", lambda: stage_validate(run_id))
        counters["transformed"] = out["records"]
        counters["rejected"] = out["rejected"]
        logs.append(f"validate: {out['records']} clean / {out['rejected']} quarantined "
                    f"/ {out.get('warnings', 0)} warnings")

        out = run_task(run_id, "load_warehouse", lambda: stage_load(run_id))
        counters["loaded"] = out["records"]
        logs.append(f"load: {out['records']} rows loaded")

        out = run_task(run_id, "data_quality_checks", lambda: stage_quality(run_id))
        quality_score = out["score"]
        logs.append(f"quality: score={out['score']} failed_checks={out['failed']}")
        if out["score"] < QUALITY_SCORE_THRESHOLD:
            logs.append(f"WARNING: quality score below threshold {QUALITY_SCORE_THRESHOLD}")

        run_task(run_id, "refresh_analytics_marts", lambda: stage_analytics(run_id))
        logs.append("analytics: marts refreshed")

        if not skip_reporting:
            out = run_task(run_id, "generate_reports", lambda: stage_reporting(run_id))
            logs.append(f"reporting: {out['records']} reports generated")

        # advance watermarks only after a fully successful run
        with get_engine().connect() as conn:
            max_ts = conn.execute(text("SELECT MAX(updated_at) FROM fact_orders")).scalar()
        if max_ts:
            set_watermark("json:orders", str(max_ts))

    except Exception as exc:
        status = "failed"
        error = str(exc)
        logs.append(f"FAILED: {exc}")
        log.error(str(exc), extra={"run_id": run_id, "dag_id": dag_id})

    finish_run(run_id, status, counters, logs, quality_score, error)
    return {"run_id": run_id, "status": status, "counters": counters,
            "quality_score": quality_score, "error": error, "log": logs}


def run_dag(dag_id: str = "daily_etl_pipeline", trigger: str = "manual",
            incremental: bool = True, skip_reporting: bool = False) -> dict:
    """Entry point used by the Airflow DAGs, the CLI and the API trigger."""
    stages = list(DAG_STAGES.get(dag_id, DAG_STAGES["daily_etl_pipeline"]))
    if skip_reporting and "reporting" in stages:
        stages.remove("reporting")
    return run_stages(dag_id, stages, trigger=trigger, incremental=incremental)
