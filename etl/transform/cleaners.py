"""Generic data-cleaning primitives (type coercion, nulls, dedupe, timestamps)."""
from __future__ import annotations

import re
from typing import Iterable

import pandas as pd

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def coerce_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def coerce_int(s: pd.Series) -> pd.Series:
    out = pd.to_numeric(s, errors="coerce")
    return out.where(out.notna(), None)


def normalize_timestamps(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Parse to UTC and store as *naive* UTC.

    The warehouse keeps every timestamp as naive UTC so that SQLite (TEXT) and
    PostgreSQL (TIMESTAMP) compare identically and string ordering stays valid.
    """
    df = df.copy()
    for col in columns:
        if col in df.columns:
            parsed = pd.to_datetime(df[col], errors="coerce", utc=True)
            df[col] = parsed.dt.tz_localize(None)
    return df


def clean_text(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    return df


def dedupe(df: pd.DataFrame, subset: Iterable[str], keep: str = "first") -> tuple[pd.DataFrame, int]:
    """Drop duplicate business keys; return (deduped, duplicate_count)."""
    before = len(df)
    df = df.drop_duplicates(subset=list(subset), keep=keep).reset_index(drop=True)
    return df, before - len(df)


def split_missing(df: pd.DataFrame, required: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (complete, missing) split on required non-null columns."""
    mask = pd.Series(True, index=df.index)
    for col in required:
        if col in df.columns:
            mask &= df[col].notna() & (df[col].astype(str).str.strip() != "")
    return df[mask].reset_index(drop=True), df[~mask].reset_index(drop=True)


def drop_null_or_invalid(df: pd.DataFrame, col: str) -> pd.DataFrame:
    return df[df[col].notna() & (df[col].astype(str).str.strip() != "")].reset_index(drop=True)


def valid_email_mask(s: pd.Series) -> pd.Series:
    return s.astype(str).str.match(EMAIL_RE)
