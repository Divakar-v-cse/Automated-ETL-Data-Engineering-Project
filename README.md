# Divakar Automated ETL Data Engineering Project

An end-to-end e-commerce data warehouse: synthetic source generation, windowed
extraction, staged transforms, SCD Type 2 dimensions, a star schema, data-quality
gating with quarantine, a FastAPI service exposing 12 endpoints, and a React +
TypeScript analytics dashboard served from the same origin.

## At a glance

| Layer | Implementation |
|---|---|
| Warehouse | SQLAlchemy Core, 22 tables (star schema + staging + operational ledgers) |
| Storage | SQLite at `data/db/warehouse.db` (dialect-aware; PostgreSQL branch present) |
| ETL | `etl/` — extract → validate → load → quality → analytics → reporting |
| Orchestration | In-repo Airflow-compatible runner: 5 DAGs, retries, run/task ledgers |
| API | FastAPI, 12 endpoints, OpenAPI at `/docs` |
| UI | React 18 + TypeScript + Vite + Tailwind + Recharts, 10 pages |
| Serving | FastAPI serves `frontend/dist` with an SPA fallback |

## Quick start

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt

python scripts/reset_db.py            # create the 22 tables
python -m etl.cli run --mode full     # seed ~100k orders
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8010 --reload
```

Frontend (only needed if you change the UI):

```bash
cd frontend
npm install
npm run build      # tsc -b && vite build -> frontend/dist
```

Then open **http://127.0.0.1:8010/**. Port 8010 is used because 8000 is often
occupied; the compose file and the Dockerfile follow the same port.

Docker:

```bash
docker compose up --build     # UI + API on http://localhost:8010
```

## Data model

Star schema:

```
dim_customer (SCD2)  dim_product (SCD2)  dim_date  dim_payment
        \                  |                 |         /
         +------------- fact_orders ----------------+
                        |  \
              fact_order_items  fact_payments  fact_shipments  fact_returns
```

- `dim_customer` and `dim_product` are SCD Type 2: `version`, `valid_from`,
  `valid_to`, `is_current`.
- `dim_payment` is a **static** payment-method lookup — it has no version or
  `is_current` columns and is not SCD2.
- Quarantine rows and the pipeline ledgers (`pipeline_runs`, `pipeline_tasks`),
  watermarks and DQ results live beside the star schema.

## API

| Method | Path |
|---|---|
| GET | `/health` |
| GET | `/api/dashboard/overview` |
| GET | `/api/analytics/sales` |
| GET | `/api/analytics/customers` |
| GET | `/api/analytics/products` |
| GET | `/api/analytics/orders` |
| GET | `/api/analytics/orders/{order_id}` |
| GET | `/api/pipeline/status` |
| GET | `/api/pipeline/history` |
| GET | `/api/data-quality` |
| GET | `/api/reports` |
| POST | `/api/pipeline/trigger` |
| POST | `/api/pipeline/backfill` |

## Dashboard pages

`/` Executive · `/sales` · `/customers` · `/products` · `/orders` ·
`/pipeline` · `/runs` · `/data-quality` · `/reports` · `/system`

## Data quality

16 checks across completeness, uniqueness, referential integrity, validity and
accuracy. Error-severity failures quarantine the row; warnings keep it. The
composite score is `(0.6 · row_integrity + 0.4 · check_pass_rate) · 100`.

Referential checks for child entities validate against the whole warehouse
(batch ∪ already-loaded orders), so incremental windows do not flag untouched
parents as orphans.

## Repository layout

```
etl/            extract / transform / load / quality / analytics / reporting
backend/app/    FastAPI app, routers, schemas, in-process runner
frontend/       React + TypeScript dashboard
data_generator/ synthetic e-commerce source data
scripts/        operational helpers (reset, probe, parity, serving checks)
airflow/        (planned) DAG definitions
dbt/            (planned) staging + mart models
database/       (planned) standalone PostgreSQL DDL
tests/          (planned) pytest suite
docs/           (planned) architecture, API, deployment, troubleshooting
```

## Status and known limitations

Verified in this environment:

- 100,000+ historical orders (`fact_orders` 99,669 rows keyed by order).
- Seeding run: 519,931 rows loaded, quality score 100.0.
- Incremental run: 197,579 rows loaded, 1,538 rejected, quality 100.0.
- All 12 endpoints return 200/202/422 as specified.
- 10 dashboard routes render live warehouse values.

Limitations, stated plainly:

- **SQLite, not PostgreSQL**, is the default store. `database/schema.sql` and
  the compose `postgres` profile are not finished, so a Postgres deployment has
  not been exercised.
- **Airflow, dbt and Spark are represented by functional equivalents**: the
  in-repo runner, reviewed SQL plus pandas transforms, and chunked pandas
  processing respectively. `airflow/`, `dbt/`, `tests/` and `docs/` are not yet
  populated.
- The Docker image has **not been built** in this environment.
- The quarantine table still holds 424,644 false-positive rows produced by an
  incremental run before the reference-set fix; they are retained for audit and
  were not deleted.

## License

No license file is included; treat the code as all rights reserved until one is
added.
