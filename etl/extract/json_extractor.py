"""JSON / JSON-Lines extraction for the order-management system."""
from __future__ import annotations

import json

import pandas as pd

from etl.config import RAW_DIR
from etl.extract.base import ExtractResult, Timer, get_watermark


def extract_jsonl(entity: str, filename: str = "orders.jsonl",
                  incremental: bool = False) -> ExtractResult:
    timer = Timer()
    path = RAW_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Source file missing: {path}")

    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    df = pd.DataFrame(rows)
    watermark = get_watermark(f"json:{entity}") if incremental else None
    if incremental and watermark and "updated_at" in df.columns:
        ts = pd.to_datetime(df["updated_at"], errors="coerce", utc=True)
        df = df[ts > pd.Timestamp(watermark, tz="UTC")]

    return ExtractResult(
        source="json", entity=entity, records=len(df),
        duration_seconds=timer.elapsed, frame=df,
        meta={"file": str(path), "incremental": incremental, "watermark": watermark},
    )


def extract_json_array(entity: str, filename: str) -> ExtractResult:
    timer = Timer()
    path = RAW_DIR / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(payload if isinstance(payload, list) else payload.get("data", []))
    return ExtractResult(source="json", entity=entity, records=len(df),
                         duration_seconds=timer.elapsed, frame=df,
                         meta={"file": str(path)})
