"""Central configuration for the Divakar Automated ETL platform.

Every path and connection string is resolved here so that the ETL jobs, the
Airflow DAGs, the dbt runner and the FastAPI backend all agree on one source of
truth.

Deployment modes
----------------
``DB_KIND=postgres``  -> production warehouse (docker-compose, PostgreSQL 16)
``DB_KIND=sqlite``    -> local functional equivalent (default on Windows hosts
                         where the Docker daemon is unavailable)
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env", override=False)

DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
STAGING_DIR = DATA_DIR / "staging"
QUARANTINE_DIR = DATA_DIR / "quarantine"
REPORT_DIR = DATA_DIR / "reports"
LOG_DIR = DATA_DIR / "logs"
DB_DIR = DATA_DIR / "db"

for _d in (RAW_DIR, STAGING_DIR, QUARANTINE_DIR, REPORT_DIR, LOG_DIR, DB_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DB_KIND = os.getenv("DB_KIND", "sqlite").lower()

POSTGRES_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://etl_user:etl_pass@localhost:5432/etl_warehouse",
)
SQLITE_PATH = Path(os.getenv("SQLITE_PATH", DB_DIR / "warehouse.db"))

# ---------------------------------------------------------------- scale knobs
N_CUSTOMERS = int(os.getenv("N_CUSTOMERS", "20000"))
N_PRODUCTS = int(os.getenv("N_PRODUCTS", "500"))
N_ORDERS = int(os.getenv("N_ORDERS", "100000"))
HISTORY_START = os.getenv("HISTORY_START", "2023-01-01")
HISTORY_END = os.getenv("HISTORY_END", "2026-10-31")
RANDOM_SEED = int(os.getenv("RANDOM_SEED", "42"))

# ------------------------------------------------------------- orchestration
PIPELINE_RETRIES = int(os.getenv("PIPELINE_RETRIES", "2"))
PIPELINE_RETRY_DELAY = float(os.getenv("PIPELINE_RETRY_DELAY", "1.0"))
QUALITY_SCORE_THRESHOLD = float(os.getenv("QUALITY_SCORE_THRESHOLD", "95.0"))

APP_NAME = "Divakar Automated ETL Data Engineering Project"
APP_VERSION = "1.0.0"


def database_url() -> str:
    """Return the SQLAlchemy URL for the active warehouse backend."""
    if DB_KIND == "postgres":
        return POSTGRES_URL
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{SQLITE_PATH.as_posix()}"
