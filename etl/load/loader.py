"""Load stage: staging tables, SCD2 merges, idempotent fact upserts, quarantine.

All writes happen inside a single database transaction per entity so a failure
half-way through cannot leave the warehouse in a partially-updated state.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from etl import schema as S
from etl.db import get_engine
from etl.transform.transformers import build_dim_date, date_key_series

CHUNK = 5000


# ------------------------------------------------------------------- utilities
def _sanitize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def records(df: pd.DataFrame, columns: list[str]) -> list[dict]:
    out: list[dict] = []
    sub = df[[c for c in columns if c in df.columns]].copy()
    for col in columns:
        if col not in sub.columns:
            sub[col] = None
    for row in sub[columns].itertuples(index=False, name=None):
        out.append({c: _sanitize(v) for c, v in zip(columns, row)})
    return out


#: hard cap on bound parameters per statement (SQLite's default limit is 32,766;
#: PostgreSQL's is 65,535).  Chunk size is derived per table from the column count.
MAX_BIND_PARAMS = 30000


def _upsert(conn: Connection, table, rows: list[dict], key_cols: list[str],
            update_cols: list[str] | None = None) -> None:
    """Dialect-aware INSERT ... ON CONFLICT DO UPDATE in chunks."""
    if not rows:
        return
    dialect = conn.dialect.name
    insert_fn = sqlite_insert if dialect == "sqlite" else pg_insert
    n_cols = max(1, len(rows[0]))
    step = max(1, min(CHUNK, MAX_BIND_PARAMS // n_cols))
    for i in range(0, len(rows), step):
        chunk = rows[i:i + step]
        stmt = insert_fn(table).values(chunk)
        if update_cols:
            stmt = stmt.on_conflict_do_update(
                index_elements=key_cols,
                set_={c: getattr(stmt.excluded, c) for c in update_cols},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=key_cols)
        conn.execute(stmt)


def _executemany(conn: Connection, stmt, rows: list[dict]) -> None:
    for i in range(0, len(rows), CHUNK):
        conn.execute(stmt, rows[i:i + CHUNK])


# ------------------------------------------------------------------- dimensions
def load_dim_date() -> int:
    df = build_dim_date("2022-01-01", "2027-12-31")
    rows = records(df, ["date_key", "full_date", "year", "quarter", "month", "month_name",
                        "day", "day_of_week", "day_name", "week_of_year", "is_weekend"])
    with get_engine().begin() as conn:
        _upsert(conn, S.dim_date, rows, ["date_key"],
                ["full_date", "year", "quarter", "month", "month_name", "day",
                 "day_of_week", "day_name", "week_of_year", "is_weekend"])
    return len(rows)


def load_dim_payment() -> int:
    """Seed the payment dimension; grain is (payment_method, provider).

    Idempotent: reruns upsert instead of re-inserting, so a restart cannot
    violate the composite natural-key constraint.
    """
    payloads = [
        ("credit_card", "Visa", "card"), ("credit_card", "Mastercard", "card"),
        ("credit_card", "Amex", "card"), ("debit_card", "Visa Debit", "card"),
        ("paypal", "PayPal", "wallet"), ("apple_pay", "Apple", "wallet"),
        ("google_pay", "Google", "wallet"), ("bank_transfer", "ACH", "bank"),
        ("bnpl", "Klarna", "credit"),
    ]
    rows = [{"payment_method": m, "provider": p, "method_group": g}
            for m, p, g in payloads]
    with get_engine().begin() as conn:
        _upsert(conn, S.dim_payment, rows, ["payment_method", "provider"],
                ["method_group"])
    return len(payloads)


def _norm(value: Any) -> str:
    """Canonical comparison form for SCD2 change detection.

    SQLite hands booleans back as 0/1 and NUMERIC as float, while the inbound
    frame carries Python/NumPy types.  Comparing canonical strings keeps a
    re-run idempotent instead of spawning a spurious new version every time.
    """
    if value is None or value is pd.NaT:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (bool, np.bool_)):
        return "1" if bool(value) else "0"
    if isinstance(value, (np.integer,)):
        return str(int(value))
    if isinstance(value, (np.floating, float)):
        return f"{round(float(value), 4)}"
    if isinstance(value, (pd.Timestamp, datetime)):
        return str(pd.Timestamp(value).to_pydatetime())[:19]
    text_value = str(value).strip()
    try:
        return f"{round(float(text_value), 4)}"
    except ValueError:
        return text_value


def scd2_merge(conn: Connection, table, df: pd.DataFrame, natural_key: str,
               attr_cols: list[str], effective_col: str = "updated_at") -> dict:
    """Slowly-Changing-Dimension Type 2 merge.

    - new natural key            -> version 1, is_current = True
    - changed attributes         -> close old row (valid_to, is_current=False),
                                    insert version n+1
    - unchanged                  -> no write (idempotent reruns are free)
    """
    if df.empty:
        return {"inserted": 0, "updated": 0, "unchanged": 0}

    cols = [table.c[natural_key], table.c["version"], table.c["is_current"]]
    cols += [table.c[c] for c in attr_cols]
    current = pd.read_sql(select(*cols).where(table.c["is_current"].is_(True)), conn)
    current = current.set_index(natural_key) if len(current) else current

    inserted, updated, unchanged = 0, 0, 0
    new_rows: list[dict] = []
    close_rows: list[dict] = []

    df = df.dropna(subset=[natural_key]).drop_duplicates(natural_key, keep="last")
    for row in df.to_dict(orient="records"):
        nk = row[natural_key]
        eff = row.get(effective_col)
        eff = pd.to_datetime(eff, errors="coerce")
        eff = datetime.utcnow() if pd.isna(eff) else eff.to_pydatetime()
        payload = {c: _sanitize(row.get(c)) for c in attr_cols}

        if nk not in current.index:
            new_rows.append({natural_key: nk, **payload, "is_current": True,
                             "valid_from": eff, "valid_to": None, "version": 1})
            inserted += 1
            continue

        cur = current.loc[nk]
        if isinstance(cur, pd.DataFrame):
            cur = cur.iloc[0]
        changed = any(_norm(cur.get(c)) != _norm(payload.get(c)) for c in attr_cols)
        if not changed:
            unchanged += 1
            continue
        close_rows.append({"nk": nk, "valid_to": eff, "version": int(cur["version"])})
        new_rows.append({natural_key: nk, **payload, "is_current": True,
                         "valid_from": eff, "valid_to": None,
                         "version": int(cur["version"]) + 1})
        updated += 1

    for cr in close_rows:
        conn.execute(
            table.update()
            .where(table.c[natural_key] == cr["nk"])
            .where(table.c["version"] == cr["version"])
            .values(is_current=False, valid_to=cr["valid_to"])
        )
    if new_rows:
        _executemany(conn, table.insert(), new_rows)
    return {"inserted": inserted, "updated": updated, "unchanged": unchanged}


def load_customers(df: pd.DataFrame) -> dict:
    attrs = ["full_name", "email", "phone", "country", "region", "city", "segment",
             "signup_date", "is_active"]
    with get_engine().begin() as conn:
        return scd2_merge(conn, S.dim_customer, df, "customer_id", attrs)


def load_products(df: pd.DataFrame) -> dict:
    attrs = ["product_name", "category", "subcategory", "brand", "unit_price",
             "unit_cost", "weight_kg", "is_active"]
    with get_engine().begin() as conn:
        return scd2_merge(conn, S.dim_product, df, "product_id", attrs)


# ------------------------------------------------------------------------ facts
def _key_maps(conn: Connection) -> dict[str, dict]:
    cust = pd.read_sql(text("SELECT customer_id, customer_key FROM dim_customer "
                            "WHERE is_current IS TRUE"), conn)
    prod = pd.read_sql(text("SELECT product_id, product_key FROM dim_product "
                            "WHERE is_current IS TRUE"), conn)
    pay = pd.read_sql(text("SELECT payment_method, provider, payment_method_key "
                           "FROM dim_payment"), conn)
    return {
        "customer": dict(zip(cust["customer_id"], cust["customer_key"])),
        "product": dict(zip(prod["product_id"], prod["product_key"])),
        "payment": {(m, p): k for m, p, k in
                    zip(pay["payment_method"], pay["provider"], pay["payment_method_key"])},
        "payment_by_method": dict(zip(pay["payment_method"], pay["payment_method_key"])),
    }


def load_staging(entity: str, df: pd.DataFrame, batch_id: int) -> int:
    table = {
        "customers": S.stg_customers, "products": S.stg_products, "orders": S.stg_orders,
        "order_items": S.stg_order_items, "payments": S.stg_payments,
        "shipments": S.stg_shipments, "returns": S.stg_returns,
    }[entity]
    cols = [c.name for c in table.columns if c.name not in ("_stg_id",)]
    df = df.copy()
    df["batch_id"] = batch_id
    rows = records(df, cols)
    with get_engine().begin() as conn:
        conn.execute(text(f"DELETE FROM {table.name}"))
        _executemany(conn, table.insert(), rows)
    return len(rows)


def load_fact_orders(df: pd.DataFrame, maps: dict) -> int:
    cols = ["order_id", "customer_key", "date_key", "channel", "currency", "status",
            "product_count", "item_count", "order_amount", "discount_amount",
            "shipping_cost", "total_amount", "order_ts", "updated_at", "ingested_at"]
    df = df.copy()
    df["customer_key"] = df["customer_id"].map(maps["customer"])
    df["date_key"] = date_key_series(df["order_ts"])
    df["ingested_at"] = datetime.utcnow()
    df = df.dropna(subset=["customer_key", "date_key"])
    rows = records(df, cols)
    with get_engine().begin() as conn:
        _upsert(conn, S.fact_orders, rows, ["order_id"],
                [c for c in cols if c != "order_id"])
    return len(rows)


def load_fact_items(df: pd.DataFrame, maps: dict, order_keys: dict) -> int:
    cols = ["order_item_id", "order_id", "order_key", "product_key", "customer_key",
            "date_key", "quantity", "unit_price", "discount_pct", "line_total", "ingested_at"]
    df = df.copy()
    df["order_key"] = df["order_id"].map(order_keys)
    df["product_key"] = df["product_id"].map(maps["product"])
    df["customer_key"] = df["customer_id"].map(maps["customer"])
    df["date_key"] = date_key_series(df["order_ts"])
    df["ingested_at"] = datetime.utcnow()
    df = df.dropna(subset=["order_key", "product_key", "date_key"])
    rows = records(df, cols)
    with get_engine().begin() as conn:
        _upsert(conn, S.fact_order_items, rows, ["order_item_id"],
                [c for c in cols if c != "order_item_id"])
    return len(rows)


def load_fact_payments(df: pd.DataFrame, maps: dict, order_keys: dict) -> int:
    cols = ["payment_id", "order_id", "order_key", "customer_key", "date_key",
            "payment_method_key", "amount", "status", "paid_at", "ingested_at"]
    df = df.copy()
    df["order_key"] = df["order_id"].map(order_keys)
    df["customer_key"] = df["customer_id"].map(maps["customer"])
    if "provider" in df.columns:
        df["payment_method_key"] = [maps["payment"].get((m, p))
                                   for m, p in zip(df["payment_method"], df["provider"])]
    else:
        df["payment_method_key"] = df["payment_method"].map(maps["payment_by_method"])
    df["payment_method_key"] = df["payment_method_key"].fillna(
        df["payment_method"].map(maps["payment_by_method"]))
    df["date_key"] = date_key_series(df["paid_at"].where(df["paid_at"].notna(), df["order_ts"]))
    df["ingested_at"] = datetime.utcnow()
    df = df.dropna(subset=["order_key", "date_key"])
    rows = records(df, cols)
    with get_engine().begin() as conn:
        _upsert(conn, S.fact_payments, rows, ["payment_id"],
                [c for c in cols if c != "payment_id"])
    return len(rows)


def load_fact_shipments(df: pd.DataFrame, order_keys: dict) -> int:
    cols = ["shipment_id", "order_id", "order_key", "date_key", "carrier",
            "tracking_number", "status", "shipped_at", "delivered_at", "shipping_cost",
            "ingested_at"]
    df = df.copy()
    df["order_key"] = df["order_id"].map(order_keys)
    df["date_key"] = date_key_series(df["shipped_at"])
    df["ingested_at"] = datetime.utcnow()
    df = df.dropna(subset=["order_key", "date_key"])
    rows = records(df, cols)
    with get_engine().begin() as conn:
        _upsert(conn, S.fact_shipments, rows, ["shipment_id"],
                [c for c in cols if c != "shipment_id"])
    return len(rows)


def load_fact_returns(df: pd.DataFrame, maps: dict, order_keys: dict) -> int:
    cols = ["return_id", "order_id", "order_key", "product_key", "date_key",
            "quantity", "reason", "refund_amount", "status", "returned_at", "ingested_at"]
    df = df.copy()
    df["order_key"] = df["order_id"].map(order_keys)
    df["product_key"] = df["product_id"].map(maps["product"])
    df["date_key"] = date_key_series(df["returned_at"])
    df["ingested_at"] = datetime.utcnow()
    df = df.dropna(subset=["order_key", "product_key", "date_key"])
    rows = records(df, cols)
    with get_engine().begin() as conn:
        _upsert(conn, S.fact_returns, rows, ["return_id"],
                [c for c in cols if c != "return_id"])
    return len(rows)


def order_key_map(conn: Connection) -> dict[str, int]:
    df = pd.read_sql(text("SELECT order_id, order_key FROM fact_orders"), conn)
    return dict(zip(df["order_id"], df["order_key"]))


def with_maps(fn):
    """Decorator: inject the dimension key maps inside a read connection."""
    def wrapper(*args, **kwargs):
        with get_engine().connect() as conn:
            maps = _key_maps(conn)
            okeys = order_key_map(conn)
        return fn(*args, maps=maps, order_keys=okeys, **kwargs)
    return wrapper


# ------------------------------------------------------------------- quarantine
def write_quarantine(run_id: int, rejected: list[dict], source: str) -> int:
    if not rejected:
        return 0
    rows = [{
        "run_id": run_id,
        "source": source,
        "entity": r["entity"],
        "record_id": r.get("record_id"),
        "reason": r["reason"],
        "severity": r.get("severity", "error"),
        "payload": r.get("payload", "{}"),
        "created_at": datetime.utcnow(),
    } for r in rejected]
    with get_engine().begin() as conn:
        _executemany(conn, S.quarantine.insert(), rows)
    return len(rows)


def quarantine_stats(conn: Connection) -> pd.DataFrame:
    return pd.read_sql(text(
        "SELECT entity, reason, COUNT(*) AS records FROM quarantine "
        "GROUP BY entity, reason ORDER BY records DESC"), conn)
