"""Read-only query helpers shared by every API router.

All numbers served to the UI come from these functions, i.e. from the warehouse
itself (marts or facts) - never from constants baked into the frontend.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping

import pandas as pd
from sqlalchemy import inspect, text

from etl.db import get_engine
from etl.logging_config import get_logger

log = get_logger("api.db", log_file="api.log")


# --------------------------------------------------------------- JSON coercion
def jsonable(value: Any) -> Any:
    """Convert pandas / numpy / Decimal scalars into JSON-safe primitives."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:  # numpy scalars
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return jsonable(value.item())
        except (AttributeError, ValueError):
            pass
    return value


def frame(sql: str, params: Mapping[str, Any] | None = None) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame (empty frame when nothing matches)."""
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=dict(params or {}))


def rows(sql: str, params: Mapping[str, Any] | None = None) -> list[dict]:
    df = frame(sql, params)
    if df.empty:
        return []
    return [{k: jsonable(v) for k, v in rec.items()} for rec in df.to_dict(orient="records")]


def one(sql: str, params: Mapping[str, Any] | None = None) -> dict | None:
    data = rows(sql, params)
    return data[0] if data else None


def scalar(sql: str, params: Mapping[str, Any] | None = None) -> Any:
    with get_engine().connect() as conn:
        value = conn.execute(text(sql), dict(params or {})).scalar()
    return jsonable(value)


def table_exists(name: str) -> bool:
    try:
        return inspect(get_engine()).has_table(name)
    except Exception:  # pragma: no cover - defensive
        return False


def table_count(name: str) -> int:
    try:
        return int(scalar(f"SELECT COUNT(*) FROM {name}") or 0)
    except Exception:
        return 0
