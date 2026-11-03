"""CSV extraction (CRM + catalog + order lines) with incremental filtering."""
from __future__ import annotations

import pandas as pd

from etl.config import RAW_DIR
from etl.extract.base import ExtractResult, Timer, get_watermark

CHUNK = 200_000


def extract_csv(entity: str, filename: str, incremental: bool = False,
                key_column: str = "updated_at") -> ExtractResult:
    timer = Timer()
    path = RAW_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Source file missing: {path}")

    frames: list[pd.DataFrame] = []
    for chunk in pd.read_csv(path, chunksize=CHUNK, low_memory=False):
        frames.append(chunk)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    total = len(df)
    watermark = get_watermark(f"csv:{entity}") if incremental else None
    if incremental and watermark and key_column in df.columns:
        ts = pd.to_datetime(df[key_column], errors="coerce", utc=True)
        df = df[ts > pd.Timestamp(watermark, tz="UTC")]
        df = df.sort_values(key_column)
    if key_column in df.columns and len(df):
        df[key_column] = df[key_column].astype(str)

    return ExtractResult(
        source="csv", entity=entity, records=len(df),
        duration_seconds=timer.elapsed, frame=df,
        meta={"file": str(path), "file_rows": total, "incremental": incremental,
              "watermark": watermark},
    )
