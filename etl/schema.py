"""Data-warehouse schema (star schema) via SQLAlchemy Core.

Defined once, executed identically against PostgreSQL (production, via
``database/schema.sql``) and SQLite (local functional equivalent).  Surrogate
integer keys keep the model portable while the natural keys remain first-class
columns for incremental lookups and referential checks.

SCD Type-2 is applied to ``dim_customer`` and ``dim_product`` using
``is_current`` / ``valid_from`` / ``valid_to`` / ``version``.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, Float, Index, Integer,
    MetaData, Numeric, String, Table, Text, UniqueConstraint,
)

from etl.config import DB_KIND
from etl.db import get_engine

metadata = MetaData()


def _pk(name: str) -> Column:
    return Column(name, Integer, primary_key=True, autoincrement=True)


# ------------------------------------------------------------------ dimensions
dim_date = Table(
    "dim_date", metadata,
    Column("date_key", Integer, primary_key=True, autoincrement=False),
    Column("full_date", Date, nullable=False, unique=True),
    Column("year", Integer, nullable=False),
    Column("quarter", Integer, nullable=False),
    Column("month", Integer, nullable=False),
    Column("month_name", String(20)),
    Column("day", Integer),
    Column("day_of_week", Integer),
    Column("day_name", String(20)),
    Column("week_of_year", Integer),
    Column("is_weekend", Boolean, default=False),
)

dim_customer = Table(
    "dim_customer", metadata,
    _pk("customer_key"),
    Column("customer_id", String(32), nullable=False, index=True),
    Column("full_name", String(120)),
    Column("email", String(160)),
    Column("phone", String(40)),
    Column("country", String(80)),
    Column("region", String(80)),
    Column("city", String(80)),
    Column("segment", String(40)),
    Column("signup_date", Date),
    Column("is_active", Boolean, default=True),
    Column("is_current", Boolean, default=True, index=True),
    Column("valid_from", DateTime, nullable=False),
    Column("valid_to", DateTime),
    Column("version", Integer, default=1),
    UniqueConstraint("customer_id", "version", name="uq_customer_version"),
)

dim_product = Table(
    "dim_product", metadata,
    _pk("product_key"),
    Column("product_id", String(32), nullable=False, index=True),
    Column("product_name", String(160)),
    Column("category", String(80)),
    Column("subcategory", String(80)),
    Column("brand", String(80)),
    Column("unit_price", Numeric(12, 2)),
    Column("unit_cost", Numeric(12, 2)),
    Column("weight_kg", Float),
    Column("is_active", Boolean, default=True),
    Column("is_current", Boolean, default=True, index=True),
    Column("valid_from", DateTime, nullable=False),
    Column("valid_to", DateTime),
    Column("version", Integer, default=1),
    UniqueConstraint("product_id", "version", name="uq_product_version"),
)

dim_payment = Table(
    "dim_payment", metadata,
    _pk("payment_method_key"),
    Column("payment_method", String(40), nullable=False, index=True),
    Column("provider", String(60), nullable=False),
    Column("method_group", String(40)),
    # grain is method x provider: one card brand is a distinct payment instrument
    UniqueConstraint("payment_method", "provider", name="uq_payment_method_provider"),
)

# --------------------------------------------------------------------- facts
fact_orders = Table(
    "fact_orders", metadata,
    _pk("order_key"),
    Column("order_id", String(32), nullable=False, unique=True, index=True),
    Column("customer_key", Integer, nullable=False, index=True),
    Column("date_key", Integer, nullable=False, index=True),
    Column("channel", String(40)),
    Column("currency", String(8)),
    Column("status", String(24), index=True),
    Column("product_count", Integer),
    Column("item_count", Integer),
    Column("order_amount", Numeric(14, 2)),
    Column("discount_amount", Numeric(14, 2)),
    Column("shipping_cost", Numeric(14, 2)),
    Column("total_amount", Numeric(14, 2)),
    Column("order_ts", DateTime, index=True),
    Column("updated_at", DateTime),
    Column("ingested_at", DateTime),
)

fact_order_items = Table(
    "fact_order_items", metadata,
    _pk("order_item_key"),
    Column("order_item_id", String(32), nullable=False, unique=True, index=True),
    Column("order_id", String(32), nullable=False, index=True),
    Column("order_key", Integer, index=True),
    Column("product_key", Integer, index=True),
    Column("customer_key", Integer, index=True),
    Column("date_key", Integer, index=True),
    Column("quantity", Integer),
    Column("unit_price", Numeric(12, 2)),
    Column("discount_pct", Numeric(5, 2)),
    Column("line_total", Numeric(14, 2)),
    Column("ingested_at", DateTime),
)

fact_payments = Table(
    "fact_payments", metadata,
    _pk("payment_key"),
    Column("payment_id", String(32), nullable=False, unique=True, index=True),
    Column("order_id", String(32), nullable=False, index=True),
    Column("order_key", Integer, index=True),
    Column("customer_key", Integer, index=True),
    Column("date_key", Integer, index=True),
    Column("payment_method_key", Integer, index=True),
    Column("amount", Numeric(14, 2)),
    Column("status", String(24), index=True),
    Column("paid_at", DateTime),
    Column("ingested_at", DateTime),
)

fact_shipments = Table(
    "fact_shipments", metadata,
    _pk("shipment_key"),
    Column("shipment_id", String(32), nullable=False, unique=True, index=True),
    Column("order_id", String(32), nullable=False, index=True),
    Column("order_key", Integer, index=True),
    Column("date_key", Integer, index=True),
    Column("carrier", String(60)),
    Column("tracking_number", String(40)),
    Column("status", String(24)),
    Column("shipped_at", DateTime),
    Column("delivered_at", DateTime),
    Column("shipping_cost", Numeric(12, 2)),
    Column("ingested_at", DateTime),
)

fact_returns = Table(
    "fact_returns", metadata,
    _pk("return_key"),
    Column("return_id", String(32), nullable=False, unique=True, index=True),
    Column("order_id", String(32), nullable=False, index=True),
    Column("order_key", Integer, index=True),
    Column("product_key", Integer, index=True),
    Column("date_key", Integer, index=True),
    Column("quantity", Integer),
    Column("reason", String(60)),
    Column("refund_amount", Numeric(12, 2)),
    Column("status", String(24)),
    Column("returned_at", DateTime),
    Column("ingested_at", DateTime),
)

# ---------------------------------------------------------------- ops tables
quarantine = Table(
    "quarantine", metadata,
    _pk("id"),
    Column("run_id", Integer, index=True),
    Column("source", String(60)),
    Column("entity", String(60)),
    Column("record_id", String(64)),
    Column("reason", String(200)),
    Column("severity", String(20)),
    Column("payload", Text),
    Column("created_at", DateTime),
)

etl_watermarks = Table(
    "etl_watermarks", metadata,
    Column("source", String(80), primary_key=True),
    Column("last_value", String(120)),
    Column("last_run_at", DateTime),
)

pipeline_runs = Table(
    "pipeline_runs", metadata,
    _pk("run_id"),
    Column("dag_id", String(120), nullable=False, index=True),
    Column("status", String(24), nullable=False, index=True),  # running/success/failed
    Column("trigger", String(24)),  # schedule/manual/backfill
    Column("started_at", DateTime, index=True),
    Column("finished_at", DateTime),
    Column("duration_seconds", Float),
    Column("records_extracted", Integer, default=0),
    Column("records_transformed", Integer, default=0),
    Column("records_loaded", Integer, default=0),
    Column("records_rejected", Integer, default=0),
    Column("quality_score", Float),
    Column("error", Text),
    Column("log", Text),
)

pipeline_tasks = Table(
    "pipeline_tasks", metadata,
    _pk("task_id"),
    Column("run_id", Integer, nullable=False, index=True),
    Column("task_name", String(160), nullable=False),
    Column("status", String(24), nullable=False),
    Column("attempt", Integer, default=1),
    Column("started_at", DateTime),
    Column("finished_at", DateTime),
    Column("duration_seconds", Float),
    Column("message", Text),
    Column("log", Text),
)

data_quality_results = Table(
    "data_quality_results", metadata,
    _pk("id"),
    Column("run_id", Integer, index=True),
    Column("check_name", String(120), nullable=False),
    Column("entity", String(60)),
    Column("status", String(20), nullable=False),  # pass/fail/warn
    Column("metric", Float),
    Column("threshold", Float),
    Column("rows_failed", Integer, default=0),
    Column("message", Text),
    Column("created_at", DateTime),
)

reports = Table(
    "reports", metadata,
    _pk("id"),
    Column("report_id", String(64), unique=True, index=True),
    Column("report_type", String(40)),  # daily/weekly
    Column("period_start", Date),
    Column("period_end", Date),
    Column("title", String(200)),
    Column("summary_json", Text),
    Column("file_path", String(300)),
    Column("generated_at", DateTime),
)

# ------------------------------------------------------------------- staging
def _staging_table(name: str, cols: dict[str, Column]) -> Table:
    cols = dict(cols)
    cols.setdefault("_stg_id", Column("_stg_id", Integer, primary_key=True, autoincrement=True))
    return Table(name, metadata, *cols.values())


stg_customers = _staging_table("stg_customers", {
    "customer_id": Column("customer_id", String(32)),
    "full_name": Column("full_name", String(120)),
    "email": Column("email", String(160)),
    "phone": Column("phone", String(40)),
    "country": Column("country", String(80)),
    "region": Column("region", String(80)),
    "city": Column("city", String(80)),
    "segment": Column("segment", String(40)),
    "signup_date": Column("signup_date", DateTime),
    "is_active": Column("is_active", Boolean),
    "updated_at": Column("updated_at", DateTime),
    "batch_id": Column("batch_id", Integer),
})

stg_products = _staging_table("stg_products", {
    "product_id": Column("product_id", String(32)),
    "product_name": Column("product_name", String(160)),
    "category": Column("category", String(80)),
    "subcategory": Column("subcategory", String(80)),
    "brand": Column("brand", String(80)),
    "unit_price": Column("unit_price", Numeric(12, 2)),
    "unit_cost": Column("unit_cost", Numeric(12, 2)),
    "weight_kg": Column("weight_kg", Float),
    "is_active": Column("is_active", Boolean),
    "updated_at": Column("updated_at", DateTime),
    "batch_id": Column("batch_id", Integer),
})

stg_orders = _staging_table("stg_orders", {
    "order_id": Column("order_id", String(32)),
    "customer_id": Column("customer_id", String(32)),
    "order_ts": Column("order_ts", DateTime),
    "channel": Column("channel", String(40)),
    "currency": Column("currency", String(8)),
    "status": Column("status", String(24)),
    "product_count": Column("product_count", Integer),
    "item_count": Column("item_count", Integer),
    "order_amount": Column("order_amount", Numeric(14, 2)),
    "discount_amount": Column("discount_amount", Numeric(14, 2)),
    "shipping_cost": Column("shipping_cost", Numeric(14, 2)),
    "total_amount": Column("total_amount", Numeric(14, 2)),
    "updated_at": Column("updated_at", DateTime),
    "batch_id": Column("batch_id", Integer),
})

stg_order_items = _staging_table("stg_order_items", {
    "order_item_id": Column("order_item_id", String(32)),
    "order_id": Column("order_id", String(32)),
    "product_id": Column("product_id", String(32)),
    "quantity": Column("quantity", Integer),
    "unit_price": Column("unit_price", Numeric(12, 2)),
    "discount_pct": Column("discount_pct", Numeric(5, 2)),
    "line_total": Column("line_total", Numeric(14, 2)),
    "updated_at": Column("updated_at", DateTime),
    "batch_id": Column("batch_id", Integer),
})

stg_payments = _staging_table("stg_payments", {
    "payment_id": Column("payment_id", String(32)),
    "order_id": Column("order_id", String(32)),
    "payment_method": Column("payment_method", String(40)),
    "provider": Column("provider", String(60)),
    "amount": Column("amount", Numeric(14, 2)),
    "status": Column("status", String(24)),
    "paid_at": Column("paid_at", DateTime),
    "updated_at": Column("updated_at", DateTime),
    "batch_id": Column("batch_id", Integer),
})

stg_shipments = _staging_table("stg_shipments", {
    "shipment_id": Column("shipment_id", String(32)),
    "order_id": Column("order_id", String(32)),
    "carrier": Column("carrier", String(60)),
    "tracking_number": Column("tracking_number", String(40)),
    "status": Column("status", String(24)),
    "shipped_at": Column("shipped_at", DateTime),
    "delivered_at": Column("delivered_at", DateTime),
    "shipping_cost": Column("shipping_cost", Numeric(12, 2)),
    "updated_at": Column("updated_at", DateTime),
    "batch_id": Column("batch_id", Integer),
})

stg_returns = _staging_table("stg_returns", {
    "return_id": Column("return_id", String(32)),
    "order_id": Column("order_id", String(32)),
    "product_id": Column("product_id", String(32)),
    "quantity": Column("quantity", Integer),
    "reason": Column("reason", String(60)),
    "refund_amount": Column("refund_amount", Numeric(12, 2)),
    "returned_at": Column("returned_at", DateTime),
    "status": Column("status", String(24)),
    "updated_at": Column("updated_at", DateTime),
    "batch_id": Column("batch_id", Integer),
})

# Cross-dialect indexes on the hot fact columns
Index("ix_fact_orders_date_status", fact_orders.c.date_key, fact_orders.c.status)
Index("ix_fact_items_order", fact_order_items.c.order_id)
Index("ix_fact_returns_order", fact_returns.c.order_id)
# NB: every index name above must be unique across the metadata; individual
# columns already carry their own ix_<table>_<column> index via index=True.

ALL_TABLES = [t for t in metadata.tables.values()]


def create_all() -> None:
    """Create every table if it does not exist (idempotent)."""
    metadata.create_all(get_engine(), checkfirst=True)


def drop_all() -> None:
    metadata.drop_all(get_engine(), checkfirst=True)


if __name__ == "__main__":  # pragma: no cover
    create_all()
    print(f"Schema created on backend: {DB_KIND}")
