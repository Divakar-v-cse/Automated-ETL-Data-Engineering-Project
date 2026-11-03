"""FastAPI application for the Divakar Automated ETL Data Engineering Project.

Serves the twelve required REST endpoints, the generated report artefacts and the
compiled React dashboard from a single origin (default http://127.0.0.1:8010).
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from etl.config import APP_NAME, APP_VERSION, DB_KIND, PROJECT_ROOT
from etl.logging_config import get_logger
from etl.schema import create_all

from .routers import analytics, dashboard, health, pipeline, quality, reports

log = get_logger("api", "api.log")

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()                      # idempotent: safe on every boot
    log.info("api starting", extra={"stage": "startup", "records": 0})
    yield
    log.info("api stopping", extra={"stage": "shutdown", "records": 0})


DESCRIPTION = """
Production-style automated e-commerce ETL platform.

**Pipeline** — CSV / JSON / REST / SQL extraction → validation & quarantine →
Type-2 dimensional load → data-quality scoring → analytics marts → reporting.

Every number returned by this API is aggregated from the warehouse at request
time; nothing is hardcoded. Trigger a run with `POST /api/pipeline/trigger`
(asynchronous, single-flight) and follow it with `GET /api/pipeline/status`.
"""

TAGS_METADATA = [
    {"name": "system", "description": "Liveness and warehouse connectivity."},
    {"name": "dashboard", "description": "Executive KPIs and trends."},
    {"name": "analytics", "description": "Sales, customer, product and order analytics."},
    {"name": "pipeline", "description": "Orchestration status, history, trigger and backfill."},
    {"name": "data-quality", "description": "Quality checks, scores and quarantine."},
    {"name": "reports", "description": "Generated daily/weekly report artefacts."},
]


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                       "http://localhost:8010", "http://127.0.0.1:8010"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("unhandled error", extra={"stage": "request"})
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "error": str(exc),
                         "request_id": request_id},
            )
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["x-request-id"] = request_id
        response.headers["x-response-time-ms"] = str(duration_ms)
        if request.url.path.startswith("/api") or request.url.path == "/health":
            log.info("request", extra={
                "stage": "request", "task": request.url.path,
                "records": response.status_code, "duration_s": duration_ms / 1000,
                "run_id": request_id,
            })
        return response

    for module in (health, dashboard, analytics, pipeline, quality, reports):
        app.include_router(module.router)

    # ---------------------------------------------------------------- frontend
    if FRONTEND_DIST.is_dir():
        assets = FRONTEND_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(FRONTEND_DIST / "index.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            """Serve real files when they exist, otherwise the SPA shell."""
            candidate = (FRONTEND_DIST / full_path).resolve()
            if (candidate.is_file()
                    and FRONTEND_DIST.resolve() in candidate.parents):
                return FileResponse(candidate)
            if full_path.startswith(("api/", "docs", "redoc", "openapi")):
                return JSONResponse(status_code=404, content={"detail": "Not found"})
            return FileResponse(FRONTEND_DIST / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def index_placeholder():
            return RedirectResponse("/docs")

    return app


app = create_app()
