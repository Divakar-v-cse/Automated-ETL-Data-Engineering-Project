"""Business-rule validation.

Two severities are enforced:

``error``    the row cannot be trusted -> it is rejected and quarantined, so it
             can never corrupt the warehouse.
``warning``  the row is usable but suspicious -> it is kept, and the finding is
             recorded once for the data-quality report.

Rules are evaluated in priority order so a rejected row is attributed to its
*first* blocking failure.  This keeps the quality report interpretable instead of
counting one broken record against five different checks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd

from etl.transform.cleaners import (
    clean_text, coerce_numeric, dedupe, normalize_timestamps, split_missing,
    valid_email_mask,
)

ORDER_STATUSES = {"pending", "confirmed", "processing", "shipped", "completed", "cancelled"}
PAYMENT_STATUSES = {"success", "failed", "pending", "refunded"}
SHIPMENT_STATUSES = {"in_transit", "delivered", "exception", "returned"}
RETURN_STATUSES = {"pending", "approved", "refunded", "rejected"}
TOTAL_TOLERANCE = 0.02

_PAYLOAD_COLS = (
    "order_id", "customer_id", "product_id", "order_item_id", "payment_id",
    "shipment_id", "return_id", "amount", "total_amount", "order_amount",
    "unit_price", "order_ts", "updated_at",
)


@dataclass
class ValidationOutcome:
    entity: str
    frame: pd.DataFrame
    rejected: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def n_valid(self) -> int:
        return len(self.frame)

    @property
    def n_rejected(self) -> int:
        return len(self.rejected)


def _rows(df: pd.DataFrame, mask: pd.Series, reasons: pd.Series,
          severities: pd.Series, id_col: str, entity: str) -> list[dict]:
    """Materialise rejected/warned rows as compact quarantine payloads."""
    if not mask.any():
        return []
    out: list[dict] = []
    bad = df[mask]
    for (_, row), reason, sev in zip(bad.iterrows(), reasons[mask], severities[mask]):
        rid = row.get(id_col)
        payload = {}
        for k in _PAYLOAD_COLS:
            if k in row.index:
                v = row[k]
                payload[k] = None if pd.isna(v) else (v if isinstance(v, (int, float)) else str(v))
        out.append({
            "entity": entity,
            "record_id": None if rid is None or pd.isna(rid) else str(rid),
            "reason": str(reason),
            "severity": str(sev),
            "payload": json.dumps(payload, default=str)[:1000],
        })
    return out


def _partition(df: pd.DataFrame, rules: list[tuple[str, pd.Series, str]],
               id_col: str, entity: str
               ) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """Apply rules; return (valid, rejected_errors, warnings).

    Blocking errors remove the row.  Warnings are attached to rows that stay
    valid, so they are observable without poisoning the warehouse.
    """
    err = pd.Series([None] * len(df), index=df.index, dtype=object)
    err_sev = pd.Series([None] * len(df), index=df.index, dtype=object)
    warn = pd.Series([None] * len(df), index=df.index, dtype=object)

    for name, mask, sev in rules:
        if mask is None:
            continue
        mask = pd.Series(mask, index=df.index).fillna(False).astype(bool)
        if sev == "error":
            newly = mask & err.isna()
            err[newly] = name
            err_sev[newly] = sev
        else:
            newly = mask & warn.isna() & err.isna()
            warn[newly] = name

    rejected = _rows(df, err.notna(), err, err_sev, id_col, entity)
    warn_mask = warn.notna() & err.isna()
    warnings = _rows(df, warn_mask, warn, pd.Series("warning", index=df.index, dtype=object),
                     id_col, entity)
    valid = df[err.isna()].reset_index(drop=True)
    return valid, rejected, warnings


def _dup_entries(entity: str, dups: int, key_label: str) -> list[dict]:
    return [{"entity": entity, "record_id": f"dup-{i}", "reason": f"duplicate_{key_label}",
             "severity": "error", "payload": "{}"} for i in range(dups)]


# --------------------------------------------------------------------- entities
def validate_customers(df: pd.DataFrame, keep: str = "first") -> ValidationOutcome:
    """``keep="last"`` is used when a base snapshot is concatenated with its
    change feed: the newest row per business key must win so the SCD2 merge can
    detect the attribute change instead of treating it as a duplicate."""
    df = clean_text(df, ["customer_id", "full_name", "email", "country", "region",
                         "city", "segment"])
    df = normalize_timestamps(df, ["signup_date", "updated_at"])
    complete, missing = split_missing(df, ["customer_id"])
    df, dups = dedupe(complete, ["customer_id"], keep=keep)

    bad_email = ~valid_email_mask(df["email"].fillna(""))
    rules = [
        ("invalid_customer_id", ~df["customer_id"].astype(str).str.match(r"^C\d{6}$"), "error"),
        ("invalid_email", bad_email, "warning"),
        ("missing_country", df["country"].isna(), "warning"),
    ]
    valid, rejected, warnings = _partition(df, rules, "customer_id", "customers")
    stats = {"duplicates_removed": 0, "missing_key": len(missing),
             "superseded_by_change_feed": 0}
    if keep == "last":
        stats["superseded_by_change_feed"] = dups
    else:
        stats["duplicates_removed"] = dups
        rejected += _dup_entries("customers", dups, "customer_id")
    return ValidationOutcome("customers", valid, rejected, warnings, stats)


def validate_products(df: pd.DataFrame, keep: str = "first") -> ValidationOutcome:
    df = clean_text(df, ["product_id", "product_name", "category", "subcategory", "brand"])
    df["unit_price"] = coerce_numeric(df["unit_price"])
    df["unit_cost"] = coerce_numeric(df["unit_cost"])
    df["weight_kg"] = coerce_numeric(df["weight_kg"])
    df = normalize_timestamps(df, ["updated_at"])
    complete, missing = split_missing(df, ["product_id"])
    df, dups = dedupe(complete, ["product_id"], keep=keep)

    rules = [
        ("invalid_product_id", ~df["product_id"].astype(str).str.match(r"^P\d{4,6}$"), "error"),
        ("negative_price", df["unit_price"] < 0, "error"),
        ("missing_price", df["unit_price"].isna(), "error"),
        ("cost_exceeds_price", df["unit_cost"] > df["unit_price"], "warning"),
        ("missing_category", df["category"].isna(), "warning"),
    ]
    valid, rejected, warnings = _partition(df, rules, "product_id", "products")
    stats = {"duplicates_removed": 0, "missing_key": len(missing),
             "superseded_by_change_feed": 0}
    if keep == "last":
        stats["superseded_by_change_feed"] = dups
    else:
        stats["duplicates_removed"] = dups
        rejected += _dup_entries("products", dups, "product_id")
    return ValidationOutcome("products", valid, rejected, warnings, stats)


def validate_orders(df: pd.DataFrame, customer_ids: set[str]) -> ValidationOutcome:
    df = clean_text(df, ["order_id", "customer_id", "channel", "currency", "status"])
    for c in ("order_amount", "discount_amount", "shipping_cost", "total_amount",
              "product_count", "item_count"):
        if c in df.columns:
            df[c] = coerce_numeric(df[c])
    df = normalize_timestamps(df, ["order_ts", "updated_at"])
    for c in ("order_amount", "discount_amount", "shipping_cost"):
        if c in df.columns:
            df[c] = df[c].fillna(0.0)

    complete, missing = split_missing(df, ["order_id", "customer_id"])
    df, dups = dedupe(complete, ["order_id"])

    expected = (df["order_amount"] - df["discount_amount"] + df["shipping_cost"]).round(2)
    mismatch = (df["total_amount"] - expected).abs() > TOTAL_TOLERANCE
    now_naive = pd.Timestamp.utcnow().tz_localize(None) + pd.Timedelta(days=1)

    rules = [
        ("missing_customer_id", df["customer_id"].isna(), "error"),
        ("invalid_timestamp", df["order_ts"].isna(), "error"),
        ("future_timestamp", df["order_ts"] > now_naive, "error"),
        ("invalid_customer_reference", ~df["customer_id"].isin(customer_ids), "error"),
        ("order_total_mismatch", mismatch, "error"),
        ("negative_order_amount", df["order_amount"] < 0, "error"),
        ("invalid_status", ~df["status"].isin(ORDER_STATUSES), "warning"),
    ]
    valid, rejected, warnings = _partition(df, rules, "order_id", "orders")
    rejected += _dup_entries("orders", dups, "order_id")
    return ValidationOutcome("orders", valid, rejected, warnings,
                             {"duplicates_removed": dups, "missing_key": len(missing),
                              "total_mismatch": int(mismatch.sum())})


def validate_order_items(df: pd.DataFrame, order_ids: set[str],
                         product_ids: set[str]) -> ValidationOutcome:
    df = clean_text(df, ["order_item_id", "order_id", "product_id"])
    for c in ("quantity", "unit_price", "discount_pct", "line_total"):
        if c in df.columns:
            df[c] = coerce_numeric(df[c])
    df = normalize_timestamps(df, ["updated_at"])
    complete, missing = split_missing(df, ["order_item_id", "order_id", "product_id"])
    df, dups = dedupe(complete, ["order_item_id"])

    rules = [
        ("invalid_order_reference", ~df["order_id"].isin(order_ids), "error"),
        ("invalid_product_reference", ~df["product_id"].isin(product_ids), "error"),
        ("negative_price", df["unit_price"] < 0, "error"),
        ("invalid_quantity", df["quantity"] <= 0, "error"),
        ("excessive_discount", df["discount_pct"].fillna(0) > 90, "warning"),
    ]
    valid, rejected, warnings = _partition(df, rules, "order_item_id", "order_items")
    rejected += _dup_entries("order_items", dups, "order_item_id")
    return ValidationOutcome("order_items", valid, rejected, warnings,
                             {"duplicates_removed": dups, "missing_key": len(missing)})


def validate_payments(df: pd.DataFrame, order_ids: set[str]) -> ValidationOutcome:
    df = clean_text(df, ["payment_id", "order_id", "payment_method", "provider", "status"])
    df["amount"] = coerce_numeric(df["amount"])
    df = normalize_timestamps(df, ["paid_at", "updated_at"])
    complete, missing = split_missing(df, ["payment_id", "order_id"])
    df, dups = dedupe(complete, ["payment_id"])

    rules = [
        ("invalid_order_reference", ~df["order_id"].isin(order_ids), "error"),
        ("negative_amount", df["amount"] < 0, "error"),
        ("invalid_status", ~df["status"].isin(PAYMENT_STATUSES), "warning"),
        ("settled_without_timestamp",
         (df["status"] == "success") & df["paid_at"].isna(), "warning"),
    ]
    valid, rejected, warnings = _partition(df, rules, "payment_id", "payments")
    rejected += _dup_entries("payments", dups, "payment_id")
    return ValidationOutcome("payments", valid, rejected, warnings,
                             {"duplicates_removed": dups, "missing_key": len(missing)})


def validate_shipments(df: pd.DataFrame, order_ids: set[str]) -> ValidationOutcome:
    df = clean_text(df, ["shipment_id", "order_id", "carrier", "tracking_number", "status"])
    df["shipping_cost"] = coerce_numeric(df["shipping_cost"])
    df = normalize_timestamps(df, ["shipped_at", "delivered_at", "updated_at"])
    complete, missing = split_missing(df, ["shipment_id", "order_id"])
    df, dups = dedupe(complete, ["shipment_id"])

    late = (df["delivered_at"].notna() & df["shipped_at"].notna()
            & (df["delivered_at"] < df["shipped_at"]))
    rules = [
        ("invalid_order_reference", ~df["order_id"].isin(order_ids), "error"),
        ("invalid_timestamp", df["shipped_at"].isna(), "error"),
        ("delivered_before_shipped", late, "error"),
        ("invalid_status", ~df["status"].isin(SHIPMENT_STATUSES), "warning"),
        ("negative_shipping_cost", df["shipping_cost"] < 0, "warning"),
    ]
    valid, rejected, warnings = _partition(df, rules, "shipment_id", "shipments")
    rejected += _dup_entries("shipments", dups, "shipment_id")
    return ValidationOutcome("shipments", valid, rejected, warnings,
                             {"duplicates_removed": dups, "missing_key": len(missing)})


def validate_returns(df: pd.DataFrame, order_ids: set[str],
                     product_ids: set[str]) -> ValidationOutcome:
    df = clean_text(df, ["return_id", "order_id", "product_id", "reason", "status"])
    df["quantity"] = coerce_numeric(df["quantity"])
    df["refund_amount"] = coerce_numeric(df["refund_amount"])
    df = normalize_timestamps(df, ["returned_at", "updated_at"])
    complete, missing = split_missing(df, ["return_id", "order_id", "product_id"])
    df, dups = dedupe(complete, ["return_id"])

    rules = [
        ("invalid_order_reference", ~df["order_id"].isin(order_ids), "error"),
        ("invalid_product_reference", ~df["product_id"].isin(product_ids), "error"),
        ("invalid_quantity", df["quantity"] <= 0, "error"),
        ("negative_refund", df["refund_amount"] < 0, "error"),
        ("invalid_timestamp", df["returned_at"].isna(), "error"),
        ("invalid_status", ~df["status"].isin(RETURN_STATUSES), "warning"),
    ]
    valid, rejected, warnings = _partition(df, rules, "return_id", "returns")
    rejected += _dup_entries("returns", dups, "return_id")
    return ValidationOutcome("returns", valid, rejected, warnings,
                             {"duplicates_removed": dups, "missing_key": len(missing)})
