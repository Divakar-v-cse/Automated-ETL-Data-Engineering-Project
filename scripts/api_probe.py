"""Probe every API endpoint, persist raw JSON and print a compact verification table.

Usage:  python scripts/api_probe.py [base_url] [out_dir]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "data/api_dumps")
OUT.mkdir(parents=True, exist_ok=True)

GETS = [
    ("health", "/health"),
    ("overview", "/api/dashboard/overview"),
    ("sales", "/api/analytics/sales"),
    ("customers", "/api/analytics/customers"),
    ("products", "/api/analytics/products"),
    ("orders", "/api/analytics/orders"),
    ("status", "/api/pipeline/status"),
    ("history", "/api/pipeline/history"),
    ("quality", "/api/data-quality"),
    ("reports", "/api/reports"),
]
POSTS = [
    ("trigger_validation", "/api/pipeline/trigger", {"dag_id": "not_a_dag"}),
    ("backfill_validation", "/api/pipeline/backfill",
     {"start_date": "2026-01-01", "end_date": "2026-09-01"}),
]


def call(name: str, path: str, body: dict | None = None, timeout: int = 180):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        status = exc.code
    except Exception as exc:  # network / timeout
        return {"name": name, "path": path, "status": "ERR", "ms": 0,
                "detail": str(exc)[:200]}
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    text = payload.decode("utf-8", "replace")
    try:
        parsed = json.loads(text)
        (OUT / f"{name}.json").write_text(
            json.dumps(parsed, indent=2)[:4_000_000], encoding="utf-8")
        detail = ""
        if isinstance(parsed, dict):
            detail = ",".join(list(parsed)[:9])
        elif isinstance(parsed, list):
            detail = f"list[{len(parsed)}]"
    except json.JSONDecodeError:
        detail = text[:120]
    return {"name": name, "path": path, "status": status, "ms": elapsed,
            "detail": detail}


def main() -> int:
    results = [call(n, p) for n, p in GETS]
    results += [call(n, p, b) for n, p, b in POSTS]
    print(f"{'endpoint':24} {'path':34} {'code':>6} {'ms':>9}  detail")
    for r in results:
        print(f"{r['name']:24} {r['path']:34} {str(r['status']):>6} "
              f"{r['ms']:>9}  {r.get('detail', '')}")
    ok = sum(1 for r in results if r["status"] in (200, 202, 409, 422))
    print(f"\nRESULT ok={ok} total={len(results)} out={OUT}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
