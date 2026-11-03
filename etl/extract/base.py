"""Shared extraction primitives: result envelope, watermark handling, timers."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import text

from etl.db import get_engine


@dataclass
class ExtractResult:
    source: str
    entity: str
    records: int
    duration_seconds: float
    frame: pd.DataFrame
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.records = len(self.frame)


class Timer:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()

    @property
    def elapsed(self) -> float:
        return round(time.perf_counter() - self.t0, 3)


def get_watermark(source: str) -> str | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT last_value FROM etl_watermarks WHERE source = :s"), {"s": source}
        ).first()
    return row[0] if row else None


def set_watermark(source: str, value: str) -> None:
    """Upsert a watermark (dialect-agnostic two-step)."""
    with get_engine().begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM etl_watermarks WHERE source = :s"), {"s": source}
        ).first()
        if exists:
            conn.execute(
                text("UPDATE etl_watermarks SET last_value = :v, last_run_at = :t WHERE source = :s"),
                {"v": str(value), "t": datetime.utcnow(), "s": source},
            )
        else:
            conn.execute(
                text("INSERT INTO etl_watermarks (source, last_value, last_run_at) "
                     "VALUES (:s, :v, :t)"),
                {"s": source, "v": str(value), "t": datetime.utcnow()},
            )
