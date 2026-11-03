"""Enrichment and conformed-dimension builders used by the load stage."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from etl.transform.validators import TOTAL_TOLERANCE


def date_key_value(ts) -> int | None:
    if ts is None or (isinstance(ts, float) and np.isnan(ts)):
        return None
    if isinstance(ts, str):
        ts = pd.to_datetime(ts, errors="coerce")
    if pd.isna(ts):
        return None
    return int(pd.Timestamp(ts).strftime("%Y%m%d"))


def date_key_series(s: pd.Series) -> pd.Series:
    ts = pd.to_datetime(s, errors="coerce")
    return ts.dt.strftime("%Y%m%d").astype("Int64")


def build_dim_date(start: str = "2022-01-01", end: str = "2027-12-31") -> pd.DataFrame:
    days = pd.date_range(start=start, end=end, freq="D")
    df = pd.DataFrame({"full_date": days.date})
    df["date_key"] = [int(d.strftime("%Y%m%d")) for d in days]
    df["year"] = days.year
    df["quarter"] = days.quarter
    df["month"] = days.month
    df["month_name"] = days.strftime("%B").to_numpy()
    df["day"] = days.day
    df["day_of_week"] = days.dayofweek + 1
    df["day_name"] = days.strftime("%A").to_numpy()
    df["week_of_year"] = days.isocalendar().week.astype(int).to_numpy()
    df["is_weekend"] = [(d >= 5) for d in days.dayofweek]
    return df[["date_key", "full_date", "year", "quarter", "month", "month_name", "day",
               "day_of_week", "day_name", "week_of_year", "is_weekend"]]


def enrich_orders(orders: pd.DataFrame) -> pd.DataFrame:
    """Add derived analytics columns before loading the fact table."""
    df = orders.copy()
    df["date_key"] = date_key_series(df["order_ts"])
    df["expected_total"] = (df["order_amount"] - df["discount_amount"]
                            + df["shipping_cost"]).round(2)
    df["total_variance"] = (df["total_amount"] - df["expected_total"]).abs()
    df["discount_rate"] = np.where(df["order_amount"] > 0,
                                   df["discount_amount"] / df["order_amount"], 0.0).round(4)
    df["order_age_days"] = (pd.Timestamp.now(tz="UTC").tz_localize(None)
                            - pd.to_datetime(df["order_ts"], utc=True).dt.tz_localize(None)).dt.days
    return df


def enrich_items(items: pd.DataFrame, orders: pd.DataFrame,
                 products: pd.DataFrame) -> pd.DataFrame:
    """Recompute authoritative line totals and attach product economics."""
    df = items.copy()
    df["recomputed_total"] = (df["unit_price"] * df["quantity"]
                              * (1 - df["discount_pct"].fillna(0))).round(2)
    df["line_total"] = np.where(df["recomputed_total"].notna() & (df["recomputed_total"] >= 0),
                                df["recomputed_total"], df["line_total"])
    meta = orders[["order_id", "order_ts", "customer_id"]].drop_duplicates("order_id")
    df = df.merge(meta, on="order_id", how="left")
    df["date_key"] = date_key_series(df["order_ts"])
    eco = products[["product_id", "unit_cost", "category"]].drop_duplicates("product_id")
    df = df.merge(eco, on="product_id", how="left")
    df["line_cost"] = (df["unit_cost"].fillna(0) * df["quantity"]).round(2)
    df["line_margin"] = (df["line_total"] - df["line_cost"]).round(2)
    return df


def enrich_payments(payments: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    df = payments.copy()
    meta = orders[["order_id", "order_ts", "customer_id"]].drop_duplicates("order_id")
    df = df.merge(meta, on="order_id", how="left")
    ts = df["paid_at"].where(df["paid_at"].notna(), df["order_ts"])
    df["date_key"] = date_key_series(ts)
    df["method_group"] = df["payment_method"].map({
        "credit_card": "card", "debit_card": "card", "paypal": "wallet",
        "apple_pay": "wallet", "google_pay": "wallet", "bank_transfer": "bank",
        "bnpl": "credit",
    }).fillna("other")
    return df


def enrich_shipments(shipments: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    df = shipments.copy()
    meta = orders[["order_id", "order_ts"]].drop_duplicates("order_id")
    df = df.merge(meta, on="order_id", how="left")
    df["date_key"] = date_key_series(df["shipped_at"])
    df["transit_days"] = (pd.to_datetime(df["delivered_at"], errors="coerce")
                          - pd.to_datetime(df["shipped_at"], errors="coerce")).dt.days
    return df


def enrich_returns(returns: pd.DataFrame, orders: pd.DataFrame,
                   products: pd.DataFrame) -> pd.DataFrame:
    df = returns.copy()
    meta = orders[["order_id", "order_ts", "customer_id"]].drop_duplicates("order_id")
    df = df.merge(meta, on="order_id", how="left")
    df["date_key"] = date_key_series(df["returned_at"])
    df["days_to_return"] = (pd.to_datetime(df["returned_at"], errors="coerce")
                            - pd.to_datetime(df["order_ts"], errors="coerce")).dt.days
    return df


def payment_dimension(payments: pd.DataFrame) -> pd.DataFrame:
    dim = (payments[["payment_method", "provider"]]
           .drop_duplicates()
           .sort_values(["payment_method", "provider"])
           .reset_index(drop=True))
    dim["method_group"] = dim["payment_method"].map({
        "credit_card": "card", "debit_card": "card", "paypal": "wallet",
        "apple_pay": "wallet", "google_pay": "wallet", "bank_transfer": "bank",
        "bnpl": "credit",
    }).fillna("other")
    return dim


def daily_aggregate(fact_orders: pd.DataFrame, dim_date: pd.DataFrame) -> pd.DataFrame:
    """Pre-computed daily sales aggregate (materialised for the analytics marts)."""
    joined = fact_orders.merge(dim_date[["date_key", "full_date"]], on="date_key", how="left")
    out = (joined.groupby("full_date")
           .agg(orders=("order_id", "nunique"),
                revenue=("total_amount", "sum"),
                gross_amount=("order_amount", "sum"),
                discount=("discount_amount", "sum"),
                shipping=("shipping_cost", "sum"))
           .reset_index())
    out["aov"] = (out["revenue"] / out["orders"].replace(0, np.nan)).round(2)
    return out
