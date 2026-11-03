"""SQL source extraction (shipment system) with incremental watermark pull.

The upstream shipment table lives in the warehouse schema as ``src_shipments``
(in production this would be a linked server / foreign DB).  Extraction uses
``SELECT ... WHERE updated_at > :watermark`` so only new/changed rows are moved.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from etl.config import RAW_DIR
from etl.db import get_engine
from etl.extract.base import ExtractResult, Timer, get_watermark, set_watermark

SOURCE_TABLE = "src_shipments"


def ensure_source_table() -> int:
    """Bootstrap the upstream shipment table from its CSV snapshot (idempotent)."""
    path = RAW_DIR / "src_shipments.csv"
    if not path.exists():
        return 0
    df = pd.read_csv(path, low_memory=False)
    engine = get_engine()
    df.to_sql(SOURCE_TABLE, engine, if_exists="replace", index=False,
              chunksize=50_000)
    return len(df)


def extract_db(entity: str, incremental: bool = True) -> ExtractResult:
    timer = Timer()
    engine = get_engine()
    watermark = get_watermark(f"db:{entity}") if incremental else None

    if incremental and watermark:
        sql = text(
            f"SELECT * FROM {SOURCE_TABLE} WHERE CAST(updated_at AS TEXT) > :wm"
        )
        df = pd.read_sql(sql, engine, params={"wm": watermark})
    else:
        df = pd.read_sql(f"SELECT * FROM {SOURCE_TABLE}", engine)

    if len(df) and "updated_at" in df.columns:
        # record the max timestamp seen as the new high-water mark
        values = pd.to_datetime(df["updated_at"], errors="coerce").dropna()
        if not values.empty:
            set_watermark(f"db:{entity}", str(values.max()))

    return ExtractResult(source="postgresql", entity=entity, records=len(df),
                         duration_seconds=timer.elapsed, frame=df,
                         meta={"table": SOURCE_TABLE, "incremental": incremental,
                               "watermark": watermark, "dialect": engine.dialect.name})
