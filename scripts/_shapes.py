"""Summarise the captured API payloads so page components can bind to real fields."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "api_dumps"

for name in ["sales", "customers", "products", "orders", "history", "quality", "reports", "overview"]:
    p = D / f"{name}.json"
    if not p.exists():
        print(name, "MISSING")
        continue
    obj = json.loads(p.read_text(encoding="utf-8"))
    print(f"== {name}  keys={list(obj.keys())}")
    for k, v in obj.items():
        if isinstance(v, list):
            if v and isinstance(v[0], dict):
                print(f"   {k}: list[{len(v)}] item_keys={list(v[0].keys())[:14]}")
            else:
                print(f"   {k}: list[{len(v)}] {v[:3]}")
        elif isinstance(v, dict):
            print(f"   {k}: dict keys={list(v.keys())[:16]}")
        else:
            print(f"   {k}: {v!r}"[:160])
    print()
