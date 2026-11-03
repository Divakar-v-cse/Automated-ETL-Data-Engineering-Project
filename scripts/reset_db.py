"""Rebuild the local warehouse from scratch (drops every table, then recreates).

Usage (from the project root):
    python scripts/reset_db.py
    python -m scripts.reset_db
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.schema import create_all, drop_all  # noqa: E402

if __name__ == "__main__":
    drop_all()
    create_all()
    print("warehouse recreated")
