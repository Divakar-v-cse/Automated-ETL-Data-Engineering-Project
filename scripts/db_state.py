"""Print a quick operational snapshot of the warehouse (runs, SCD2 versions, marts)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from etl.config import SQLITE_PATH  # noqa: E402

con = sqlite3.connect(str(SQLITE_PATH))


def q(sql: str):
    try:
        return con.execute(sql).fetchall()
    except Exception as exc:  # pragma: no cover - diagnostic helper
        return [("ERR", str(exc)[:120])]


print("runs:", q("SELECT run_id, dag_id, status, trigger, records_loaded, "
                 "quality_score, duration_seconds FROM pipeline_runs ORDER BY run_id"))
print()
print("tasks_run2:", q("SELECT task_name, status, attempt, round(duration_seconds,1) "
                       "FROM pipeline_tasks WHERE run_id=2 ORDER BY task_id"))
print()
for dim in ("dim_customer", "dim_product", "dim_payment"):
    print(f"scd_{dim}:", q(f"SELECT version, COUNT(*), SUM(is_current) FROM {dim} "
                           f"GROUP BY version ORDER BY version"))
print()
print("current_dims:", q("SELECT (SELECT COUNT(*) FROM dim_customer WHERE is_current), "
                         " (SELECT COUNT(*) FROM dim_product WHERE is_current), "
                         " (SELECT COUNT(*) FROM dim_payment WHERE is_current)"))
print()
marts = [r[0] for r in q("SELECT name FROM sqlite_master WHERE type='table' "
                         "AND (name LIKE 'mart_%') ORDER BY name")]
for m in marts:
    print(f"  {m}: {q(f'SELECT COUNT(*) FROM {m}')[0][0]}")
print()
print("watermarks:", q("SELECT source, last_value, last_run_at FROM etl_watermarks"))
print("quarantine:", q("SELECT COUNT(*) FROM quarantine_records"))
print("quality_runs:", q("SELECT run_id, score, passed, failed FROM quality_runs "
                        "ORDER BY run_id"))
con.close()
