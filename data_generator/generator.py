"""Synthetic-but-realistic e-commerce source data generator.

Produces the six upstream systems described in the business scenario:

==============  ==========================================================
Source          File / channel
==============  ==========================================================
CRM             ``data/raw/customers.csv`` (+ ``customers_updates.csv``)
Catalog         ``data/raw/products.csv``  (+ ``products_updates.csv``)
Orders          ``data/raw/orders.jsonl``
Order lines     ``data/raw/order_items.csv``
Payments        ``data/raw/api/payments_page_*.json``  (REST API source)
Shipments       ``src_shipments`` DB table             (SQL source)
Returns         ``data/raw/returns.csv``
==============  ==========================================================

A controlled defect injection rate (``DEFECT_RATE``) plants duplicates, nulls,
negative prices, broken foreign keys and corrupt timestamps so that the
data-quality layer has genuine work to do.

Usage
-----
    python -m data_generator.generator --orders 100000
    python -m data_generator.generator --incremental --days 1
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from etl.config import (
    HISTORY_END,
    HISTORY_START,
    N_CUSTOMERS,
    N_ORDERS,
    N_PRODUCTS,
    RANDOM_SEED,
    RAW_DIR,
)

DEFECT_RATE = 0.0035  # ~0.35% of rows carry a planted defect

CATEGORIES = {
    "Electronics": ["Headphones", "Smartphones", "Laptops", "Cameras", "Wearables"],
    "Home & Kitchen": ["Cookware", "Small Appliances", "Storage", "Bedding", "Lighting"],
    "Fashion": ["Footwear", "Outerwear", "Accessories", "Activewear", "Bags"],
    "Beauty": ["Skincare", "Haircare", "Fragrance", "Makeup"],
    "Sports": ["Fitness", "Cycling", "Outdoor", "Team Sports"],
    "Books": ["Fiction", "Non-Fiction", "Technical", "Children"],
}

REGIONS = {
    "North America": [("United States", ["New York", "Chicago", "Austin", "Seattle", "Miami"]),
                      ("Canada", ["Toronto", "Vancouver", "Montreal"])],
    "Europe": [("United Kingdom", ["London", "Manchester", "Leeds"]),
               ("Germany", ["Berlin", "Munich", "Hamburg"]),
               ("France", ["Paris", "Lyon", "Toulouse"]),
               ("Netherlands", ["Amsterdam", "Rotterdam"])],
    "Asia Pacific": [("India", ["Mumbai", "Bengaluru", "Delhi", "Pune", "Chennai"]),
                     ("Australia", ["Sydney", "Melbourne", "Brisbane"]),
                     ("Japan", ["Tokyo", "Osaka"])],
    "LATAM": [("Brazil", ["Sao Paulo", "Rio de Janeiro"]),
              ("Mexico", ["Mexico City", "Guadalajara"])],
}

CHANNELS = ["web", "mobile_app", "marketplace", "phone", "partner_api"]
SEGMENTS = ["consumer", "smb", "enterprise", "vip"]
PAY_METHODS = [("credit_card", "Visa"), ("credit_card", "Mastercard"), ("credit_card", "Amex"),
               ("debit_card", "Visa Debit"), ("paypal", "PayPal"), ("apple_pay", "Apple"),
               ("google_pay", "Google"), ("bank_transfer", "ACH"), ("bnpl", "Klarna")]
CARRIERS = ["FedEx", "UPS", "DHL", "USPS", "BlueDart", "Local Courier"]
RETURN_REASONS = ["damaged", "wrong_item", "not_as_described", "late_delivery",
                  "changed_mind", "quality_issue"]

FIRST = ["Aarav", "Priya", "James", "Olivia", "Liam", "Emma", "Noah", "Ava", "Rohan", "Sofia",
         "Lucas", "Mia", "Ethan", "Isabella", "Arjun", "Zara", "Mateo", "Chloe", "Kenji", "Amara",
         "Daniel", "Grace", "Omar", "Leila", "Viktor", "Nina", "Hugo", "Clara", "Diego", "Hana"]
LAST = ["Sharma", "Patel", "Smith", "Johnson", "Brown", "Garcia", "Miller", "Davis", "Kumar",
        "Rodriguez", "Martinez", "Wilson", "Anderson", "Taylor", "Thomas", "Moore", "Jackson",
        "Martin", "Lee", "Perez", "Nguyen", "Clark", "Lewis", "Walker", "Hall", "Young"]
ADJ = ["Ultra", "Pro", "Max", "Eco", "Prime", "Nova", "Aero", "Flex", "Titan", "Zen", "Core", "Edge"]
NOUN = ["Speaker", "Lamp", "Jacket", "Blender", "Sneaker", "Backpack", "Monitor", "Chair",
        "Watch", "Camera", "Kettle", "Mug", "Tablet", "Keyboard", "Tripod", "Mat"]


def _names(rng: np.random.Generator, n: int) -> np.ndarray:
    return np.array([f"{FIRST[i % len(FIRST)]} {LAST[(i * 7) % len(LAST)]}" for i in range(n)])


def generate_customers(n: int, rng: np.random.Generator) -> pd.DataFrame:
    regions = list(REGIONS)
    reg = rng.choice(regions, size=n, p=[0.34, 0.28, 0.26, 0.12])
    countries, cities = [], []
    for r in reg:
        c, city_list = REGIONS[r][rng.integers(0, len(REGIONS[r]))]
        countries.append(c)
        cities.append(city_list[int(rng.integers(0, len(city_list)))])

    start = datetime.fromisoformat(HISTORY_START)
    span = (datetime.fromisoformat(HISTORY_END) - start).days
    signup = [start + timedelta(days=int(d)) for d in rng.integers(0, span, size=n)]

    cid = [f"C{i:06d}" for i in range(1, n + 1)]
    emails = [f"{c.split()[0].lower()}.{c.split()[1].lower()}{i}@example.com"
              for i, c in enumerate(_names(rng, n), start=1)]

    df = pd.DataFrame({
        "customer_id": cid,
        "full_name": _names(rng, n),
        "email": emails,
        "phone": [f"+1-555-{i:04d}" for i in rng.integers(1000, 9999, size=n)],
        "country": countries,
        "region": reg,
        "city": cities,
        "segment": rng.choice(SEGMENTS, size=n, p=[0.62, 0.24, 0.09, 0.05]),
        "signup_date": signup,
        "is_active": rng.choice([True, False], size=n, p=[0.93, 0.07]),
        "updated_at": [s + timedelta(days=int(d)) for s, d in zip(signup, rng.integers(1, 400, size=n))],
    })
    return df


def generate_products(n: int, rng: np.random.Generator) -> pd.DataFrame:
    cats = list(CATEGORIES)
    cat = rng.choice(cats, size=n, p=[0.24, 0.2, 0.22, 0.12, 0.12, 0.10])
    sub = [CATEGORIES[c][int(rng.integers(0, len(CATEGORIES[c])))] for c in cat]
    base = np.round(rng.lognormal(mean=4.1, sigma=0.55, size=n), 2)
    base = np.clip(base, 4.99, 1199.0)
    margin = rng.uniform(0.32, 0.62, size=n)

    names = [f"{ADJ[i % len(ADJ)]} {sub[i]} {i:03d}" for i in range(n)]
    return pd.DataFrame({
        "product_id": [f"P{i:04d}" for i in range(1, n + 1)],
        "product_name": names,
        "category": cat,
        "subcategory": sub,
        "brand": [f"Brand{chr(65 + i % 26)}" for i in range(n)],
        "unit_price": base,
        "unit_cost": np.round(base * (1 - margin), 2),
        "weight_kg": np.round(rng.uniform(0.1, 12.0, size=n), 2),
        "is_active": rng.choice([True, False], size=n, p=[0.94, 0.06]),
        "updated_at": [datetime.fromisoformat(HISTORY_START) + timedelta(days=int(d))
                       for d in rng.integers(0, 60, size=n)],
    })


def generate_orders(products: pd.DataFrame, customers: pd.DataFrame,
                    n: int, rng: np.random.Generator,
                    start: datetime, end: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create orders + order items with a growth trend and weekday seasonality."""
    days = pd.date_range(start=start, end=end, freq="D")
    # geometric growth from 0.6x to 1.6x with weekly rhythm + November peak
    t = np.linspace(0, 1, len(days))
    trend = 0.6 + 1.0 * t
    dow = np.array([1.0, 1.02, 1.04, 1.08, 1.18, 1.30, 0.92])  # Mon..Sun
    weekly = dow[days.dayofweek.values]
    holiday = np.where(days.month.isin([11, 12]), 1.35, 1.0)
    weights = trend * weekly * holiday
    probs = weights / weights.sum()

    day_idx = rng.choice(len(days), size=n, p=probs)
    # ~25% of buyers are power users (Pareto-ish repeat behaviour)
    cust_pool = customers["customer_id"].to_numpy()
    cust_w = np.where(rng.random(len(cust_pool)) < 0.25, 6.0, 1.0)
    cust_idx = rng.choice(len(cust_pool), size=n, p=cust_w / cust_w.sum())

    # time of day: business hours weighted
    hour_w = np.array([1, 1, 1, 1, 1, 2, 3, 5, 7, 9, 10, 10, 9, 8, 8, 8, 8, 8, 8, 7, 6, 5, 3, 2],
                      dtype=float)
    hour = rng.choice(24, size=n, p=hour_w / hour_w.sum())
    minute = rng.integers(0, 60, size=n)
    order_ts = [days[d].to_pydatetime().replace(hour=int(h), minute=int(m))
                for d, h, m in zip(day_idx, hour, minute)]

    n_items = rng.choice([1, 2, 3, 4, 5], size=n, p=[0.34, 0.32, 0.20, 0.10, 0.04])
    total_items = int(n_items.sum())

    oid = np.array([f"O{i:08d}" for i in range(1, n + 1)])
    item_order = np.repeat(oid, n_items)
    item_cust = np.repeat(cust_idx, n_items)

    prod_idx = rng.integers(0, len(products), size=total_items)
    unit_price = products["unit_price"].to_numpy()[prod_idx]
    # small price drift over time
    unit_price = np.round(unit_price * rng.uniform(0.93, 1.07, size=total_items), 2)
    qty = rng.choice([1, 1, 1, 2, 2, 3], size=total_items)
    disc = np.round(rng.choice([0.0, 0.0, 0.0, 0.05, 0.10, 0.15, 0.20, 0.25],
                               size=total_items), 2)
    line_total = np.round(unit_price * qty * (1 - disc), 2)

    items = pd.DataFrame({
        "order_item_id": [f"OI{i:09d}" for i in range(1, total_items + 1)],
        "order_id": item_order,
        "product_id": products["product_id"].to_numpy()[prod_idx],
        "quantity": qty,
        "unit_price": unit_price,
        "discount_pct": disc,
        "line_total": line_total,
        "updated_at": [order_ts[0]] * total_items,
    })
    ts_by_order = dict(zip(oid, order_ts))
    items["order_ts"] = items["order_id"].map(ts_by_order)
    items["updated_at"] = items["order_ts"]

    # aggregate to order header
    agg = items.groupby("order_id", sort=False).agg(
        product_count=("product_id", "nunique"),
        item_count=("quantity", "sum"),
        order_amount=("line_total", "sum"),
    ).reset_index()

    headers = pd.DataFrame({
        "order_id": oid,
        "customer_id": cust_pool[cust_idx],
        "order_ts": order_ts,
        "channel": rng.choice(CHANNELS, size=n, p=[0.42, 0.33, 0.15, 0.05, 0.05]),
        "currency": "USD",
    }).merge(agg, on="order_id", how="left")

    headers["discount_amount"] = np.round(
        headers["order_amount"] * rng.choice([0.0, 0.0, 0.03, 0.05, 0.08, 0.12], size=n), 2)
    headers["shipping_cost"] = np.round(
        np.where(rng.random(n) < 0.3, 0.0, rng.uniform(3.5, 24.0, size=n)), 2)
    headers["total_amount"] = np.round(
        headers["order_amount"] - headers["discount_amount"] + headers["shipping_cost"], 2)

    # order status depends on age
    age_days = (pd.Timestamp(end) - pd.to_datetime(headers["order_ts"])).dt.days.to_numpy()
    status = np.where(age_days > 30, "completed", "processing")
    status = np.where((age_days > 3) & (age_days <= 30), "shipped", status)
    status = np.where((age_days <= 3) & (age_days > 0), "confirmed", status)
    cancel = rng.random(n) < 0.035
    status = np.where(cancel, "cancelled", status)
    headers["status"] = status
    headers["updated_at"] = headers["order_ts"]

    return headers, items


def generate_payments(orders: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    n = len(orders)
    method_idx = rng.integers(0, len(PAY_METHODS), size=n)
    roll = rng.random(n)
    status = np.where(roll < 0.945, "success", np.where(roll < 0.985, "failed", "pending"))
    paid_at = orders["order_ts"].to_numpy()
    # failed / pending payments have no settlement timestamp
    paid_at = np.where(status == "success", paid_at, None)
    return pd.DataFrame({
        "payment_id": [f"PAY{i:09d}" for i in range(1, n + 1)],
        "order_id": orders["order_id"].to_numpy(),
        "payment_method": [PAY_METHODS[i][0] for i in method_idx],
        "provider": [PAY_METHODS[i][1] for i in method_idx],
        "amount": orders["total_amount"].to_numpy(),
        "status": status,
        "paid_at": paid_at,
        "updated_at": orders["updated_at"].to_numpy(),
    })


def generate_shipments(orders: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    shippable = orders[orders["status"] != "cancelled"].copy()
    n = len(shippable)
    ship_ts = pd.to_datetime(shippable["order_ts"]) + pd.to_timedelta(
        rng.integers(1, 4, size=n), unit="D")
    transit = rng.integers(2, 9, size=n)
    delivered = ship_ts + pd.to_timedelta(transit, unit="D")
    now = pd.Timestamp(HISTORY_END)
    status = np.where(delivered <= now, "delivered", "in_transit")
    status = np.where(rng.random(n) < 0.02, "exception", status)
    delivered = np.where(status == "delivered", delivered, None)
    return pd.DataFrame({
        "shipment_id": [f"SHP{i:09d}" for i in range(1, n + 1)],
        "order_id": shippable["order_id"].to_numpy(),
        "carrier": rng.choice(CARRIERS, size=n),
        "tracking_number": [f"TRK{rng.integers(10**9, 10**10)}" for _ in range(n)],
        "status": status,
        "shipped_at": ship_ts.to_numpy(),
        "delivered_at": delivered,
        "shipping_cost": shippable["shipping_cost"].to_numpy(),
        "updated_at": np.where(pd.isna(delivered), ship_ts, delivered),
    })


def generate_returns(orders: pd.DataFrame, items: pd.DataFrame,
                     rng: np.random.Generator) -> pd.DataFrame:
    eligible = orders[orders["status"].isin(["completed", "shipped"])]["order_id"].to_numpy()
    n = max(1, int(len(eligible) * 0.075))
    picked = rng.choice(eligible, size=n, replace=True)
    item_pool = items[items["order_id"].isin(picked)]
    sample = item_pool.sample(n=min(n, len(item_pool)), random_state=RANDOM_SEED)
    ret_ts = pd.to_datetime(sample["order_ts"]) + pd.to_timedelta(
        rng.integers(3, 40, size=len(sample)), unit="D")
    return pd.DataFrame({
        "return_id": [f"RET{i:08d}" for i in range(1, len(sample) + 1)],
        "order_id": sample["order_id"].to_numpy(),
        "product_id": sample["product_id"].to_numpy(),
        "quantity": rng.integers(1, 3, size=len(sample)),
        "reason": rng.choice(RETURN_REASONS, size=len(sample)),
        "refund_amount": np.round(sample["line_total"].to_numpy() * rng.uniform(0.5, 1.0, size=len(sample)), 2),
        "returned_at": ret_ts.to_numpy(),
        "status": rng.choice(["approved", "refunded", "pending"], size=len(sample), p=[0.45, 0.5, 0.05]),
        "updated_at": ret_ts.to_numpy(),
    })


def inject_defects(orders: pd.DataFrame, items: pd.DataFrame,
                   rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Plant realistic upstream defects so the DQ layer has real work to do."""
    orders = orders.copy()
    items = items.copy()
    n = len(orders)
    k = max(5, int(n * DEFECT_RATE))

    # 1) exact duplicate order rows
    dup_idx = rng.choice(n, size=max(3, k // 3), replace=False)
    orders = pd.concat([orders, orders.iloc[dup_idx]], ignore_index=True)

    # 2) null customer (orphan order)
    null_idx = rng.choice(n, size=max(3, k // 4), replace=False)
    orders.loc[null_idx, "customer_id"] = None

    # 3) broken customer FK
    bad_fk = rng.choice(n, size=max(3, k // 4), replace=False)
    orders.loc[bad_fk, "customer_id"] = "C999999"

    # 4) corrupt timestamp
    ts_idx = rng.choice(n, size=max(3, k // 5), replace=False)
    orders["order_ts"] = orders["order_ts"].astype(object)
    orders.loc[ts_idx, "order_ts"] = "not-a-timestamp"

    # 5) order total mismatch
    tot_idx = rng.choice(n, size=max(3, k // 4), replace=False)
    orders.loc[tot_idx, "total_amount"] = (
        pd.to_numeric(orders.loc[tot_idx, "total_amount"], errors="coerce") + 137.5
    ).round(2)

    # 6) negative price on a few line items
    neg_idx = rng.choice(len(items), size=max(3, k // 3), replace=False)
    items.loc[neg_idx, "unit_price"] = -abs(items.loc[neg_idx, "unit_price"])
    items.loc[neg_idx, "line_total"] = -abs(items.loc[neg_idx, "line_total"])

    return orders, items


def write_sources(customers: pd.DataFrame, products: pd.DataFrame, orders: pd.DataFrame,
                  items: pd.DataFrame, payments: pd.DataFrame, shipments: pd.DataFrame,
                  returns: pd.DataFrame, out: Path, rng: np.random.Generator) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    api_dir = out / "api"
    api_dir.mkdir(exist_ok=True)

    customers.to_csv(out / "customers.csv", index=False)
    products.to_csv(out / "products.csv", index=False)
    items.drop(columns=["order_ts"]).to_csv(out / "order_items.csv", index=False)
    returns.to_csv(out / "returns.csv", index=False)
    shipments.to_csv(out / "src_shipments.csv", index=False)

    # Orders as JSON Lines (streaming-friendly JSON source)
    with open(out / "orders.jsonl", "w", encoding="utf-8") as fh:
        for rec in orders.to_dict(orient="records"):
            fh.write(json.dumps(rec, default=str) + "\n")

    # Payments via a paged REST payload (mock upstream payment gateway)
    page_size = 5000
    records = payments.to_dict(orient="records")
    pages = 0
    for i in range(0, len(records), page_size):
        pages += 1
        chunk = records[i:i + page_size]
        payload = {
            "page": pages,
            "page_size": page_size,
            "total_records": len(records),
            "has_more": i + page_size < len(records),
            "data": [{k: (None if pd.isna(v) else str(v) if isinstance(v, pd.Timestamp) else v)
                      for k, v in r.items()} for r in chunk],
        }
        (api_dir / f"payments_page_{pages:03d}.json").write_text(
            json.dumps(payload, default=str), encoding="utf-8")

    # SCD2 snapshots: ~10% of customers and ~15% of products change
    upd_c = customers.sample(frac=0.10, random_state=RANDOM_SEED).copy()
    upd_c["segment"] = rng.choice(["vip", "enterprise", "smb", "consumer"], size=len(upd_c))
    upd_c["city"] = [
        REGIONS[r][0][1][0] for r in upd_c["region"]
    ]
    upd_c["updated_at"] = [datetime.fromisoformat(HISTORY_END) - timedelta(days=int(d))
                           for d in rng.integers(0, 60, size=len(upd_c))]
    upd_c.to_csv(out / "customers_updates.csv", index=False)

    upd_p = products.sample(frac=0.15, random_state=RANDOM_SEED).copy()
    upd_p["unit_price"] = np.round(upd_p["unit_price"] * rng.uniform(1.05, 1.20, size=len(upd_p)), 2)
    upd_p["updated_at"] = [datetime.fromisoformat(HISTORY_END) - timedelta(days=int(d))
                           for d in rng.integers(0, 45, size=len(upd_p))]
    upd_p.to_csv(out / "products_updates.csv", index=False)

    return {
        "customers": len(customers),
        "customers_updates": len(upd_c),
        "products": len(products),
        "products_updates": len(upd_p),
        "orders": len(orders),
        "order_items": len(items),
        "payments": len(payments),
        "shipments": len(shipments),
        "returns": len(returns),
        "payment_pages": pages,
    }


def build(n_orders: int = N_ORDERS, n_customers: int = N_CUSTOMERS,
          n_products: int = N_PRODUCTS, out: Path = RAW_DIR,
          seed: int = RANDOM_SEED,
          start: str = HISTORY_START, end: str = HISTORY_END,
          defects: bool = True) -> dict:
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)

    customers = generate_customers(n_customers, rng)
    products = generate_products(n_products, rng)
    orders, items = generate_orders(products, customers, n_orders, rng,
                                    datetime.fromisoformat(start), datetime.fromisoformat(end))
    payments = generate_payments(orders, rng)
    shipments = generate_shipments(orders, rng)
    returns = generate_returns(orders, items, rng)

    if defects:
        orders, items = inject_defects(orders, items, rng)

    counts = write_sources(customers, products, orders, items, payments,
                           shipments, returns, out, rng)
    counts["duration_seconds"] = round(time.perf_counter() - t0, 2)
    counts["generated_at"] = datetime.utcnow().isoformat() + "Z"
    (out / "manifest.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")
    return counts


def build_incremental(days: int = 1, out: Path = RAW_DIR, seed: int | None = None) -> dict:
    """Append new orders for the last ``days`` days (simulates live traffic)."""
    rng = np.random.default_rng(seed or int(time.time()))
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    products = pd.read_csv(out / "products.csv")
    customers = pd.read_csv(out / "customers.csv")
    n = max(50, days * 380)

    orders, items = generate_orders(products, customers, n, rng,
                                    datetime.combine(start, datetime.min.time()),
                                    datetime.combine(end, datetime.min.time()))
    base = pd.read_csv(out / "customers.csv")["customer_id"].nunique()
    offset = 10**8
    orders["order_id"] = "O" + (np.arange(len(orders)) + offset).astype(str)
    mapping = dict(zip(items["order_id"].unique(), orders["order_id"]))
    items["order_id"] = items["order_id"].map(mapping)
    items["order_item_id"] = "OI" + (np.arange(len(items)) + offset * 10).astype(str)

    payments = generate_payments(orders, rng)
    payments["payment_id"] = "PAY" + (np.arange(len(payments)) + offset).astype(str)
    shipments = generate_shipments(orders, rng)
    shipments["shipment_id"] = "SHP" + (np.arange(len(shipments)) + offset).astype(str)

    with open(out / "orders.jsonl", "a", encoding="utf-8") as fh:
        for rec in orders.to_dict(orient="records"):
            fh.write(json.dumps(rec, default=str) + "\n")
    items.drop(columns=["order_ts"]).to_csv(out / "order_items.csv", mode="a", header=False, index=False)
    shipments.to_csv(out / "src_shipments.csv", mode="a", header=False, index=False)

    page = len(list((out / "api").glob("payments_page_*.json"))) + 1
    payload = {"page": page, "page_size": len(payments), "total_records": len(payments),
               "has_more": False,
               "data": [{k: (None if pd.isna(v) else v) for k, v in r.items()}
                        for r in payments.to_dict(orient="records")]}
    (out / "api" / f"payments_page_{page:03d}.json").write_text(
        json.dumps(payload, default=str), encoding="utf-8")

    return {"orders": len(orders), "order_items": len(items), "payments": len(payments),
            "shipments": len(shipments), "customers_known": base, "days": days}


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate e-commerce source data")
    ap.add_argument("--orders", type=int, default=N_ORDERS)
    ap.add_argument("--customers", type=int, default=N_CUSTOMERS)
    ap.add_argument("--products", type=int, default=N_PRODUCTS)
    ap.add_argument("--seed", type=int, default=RANDOM_SEED)
    ap.add_argument("--start", default=HISTORY_START)
    ap.add_argument("--end", default=HISTORY_END)
    ap.add_argument("--no-defects", action="store_true")
    ap.add_argument("--incremental", action="store_true")
    ap.add_argument("--days", type=int, default=1)
    args = ap.parse_args()

    if args.incremental:
        print(json.dumps(build_incremental(args.days), indent=2))
    else:
        print(json.dumps(build(args.orders, args.customers, args.products,
                               seed=args.seed, start=args.start, end=args.end,
                               defects=not args.no_defects), indent=2))


if __name__ == "__main__":
    main()
