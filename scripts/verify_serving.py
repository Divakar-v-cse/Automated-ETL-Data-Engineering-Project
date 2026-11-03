"""Verify FastAPI serves the compiled SPA and that the API behind it returns real rows."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010"
ROUTES = ["/", "/sales", "/customers", "/products", "/orders",
          "/pipeline", "/runs", "/data-quality", "/reports", "/system"]


def get(path: str, timeout: int = 120):
    req = urllib.request.Request(BASE + path, headers={"Accept": "*/*"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, resp.headers.get("content-type", ""), body, \
                round((time.perf_counter() - started) * 1000, 1)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", ""), exc.read(), \
            round((time.perf_counter() - started) * 1000, 1)


def main() -> None:
    print("=== SPA shell ===")
    status, ctype, body, ms = get("/")
    html = body.decode("utf-8", "replace")
    print(f"GET / -> {status} {ctype} {ms}ms bytes={len(body)}")
    print(f"  has #root      : {'id=\"root\"' in html}")
    print(f"  has js bundle  : {'index-BRHN9fi9.js' in html}")
    print(f"  has css bundle : {'index-BTli-31B.css' in html}")

    print("\n=== static assets ===")
    for asset in ("/assets/index-BRHN9fi9.js", "/assets/index-BTli-31B.css"):
        s, ct, b, m = get(asset)
        print(f"GET {asset} -> {s} {ct} {m}ms bytes={len(b)}")

    print("\n=== client routes (SPA fallback) ===")
    ok = 0
    for route in ROUTES:
        s, ct, b, m = get(route)
        served = 'id="root"' in b.decode("utf-8", "replace")
        ok += 1 if (s == 200 and served) else 0
        print(f"GET {route:15s} -> {s} {m:>8}ms shell={served}")

    print(f"\nRESULT routes_served={ok}/{len(ROUTES)}")

    print("\n=== API data behind the dashboard ===")
    s, ct, b, m = get("/api/dashboard/overview")
    if s == 200:
        payload = json.loads(b)
        k = payload.get("kpis", {})
        print(f"GET /api/dashboard/overview -> {s} {m}ms")
        print("  kpis:", json.dumps({kk: k.get(kk) for kk in list(k)[:8]}, default=str))
        print("  window:", json.dumps(payload.get("window", {}), default=str))
        rev = payload.get("revenue_series") or payload.get("daily_revenue") or []
        print(f"  revenue series points: {len(rev)}")
        tops = payload.get("top_products") or payload.get("top_categories") or []
        print(f"  top_products rows: {len(tops)}")
    else:
        print(f"GET /api/dashboard/overview -> {s}")

    s, ct, b, m = get("/api/analytics/sales")
    if s == 200:
        payload = json.loads(b)
        print(f"GET /api/analytics/sales -> {s} {m}ms keys={sorted(payload)[:10]}")
        for key in ("revenue_by_month", "revenue_series", "monthly", "daily"):
            if isinstance(payload.get(key), list):
                print(f"  {key}: {len(payload[key])} points")
    else:
        print(f"GET /api/analytics/sales -> {s}")

    s, ct, b, m = get("/api/health" if False else "/health")
    print(f"GET /health -> {s} {m}ms")
    if s == 200:
        print("  ", json.dumps(json.loads(b), default=str)[:400])


if __name__ == "__main__":
    main()
