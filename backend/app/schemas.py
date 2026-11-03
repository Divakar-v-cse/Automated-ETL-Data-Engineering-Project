"""Pydantic contracts for the Divakar Automated ETL API.

Request models carry validation (date windows, page sizes, sort keys); response
models document the payload shape in the generated OpenAPI schema.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DagId = Literal[
    "daily_etl_pipeline",
    "incremental_ingestion_pipeline",
    "data_quality_pipeline",
    "analytics_pipeline",
    "reporting_pipeline",
]


# ------------------------------------------------------------------- requests
class TriggerRequest(BaseModel):
    """Body for ``POST /api/pipeline/trigger``."""

    dag_id: DagId = Field("daily_etl_pipeline", description="Workflow to execute")
    incremental: bool = Field(True, description="Watermark-based extraction when true")
    skip_reporting: bool = Field(False, description="Skip the reporting stage")
    mode: Literal["async", "sync"] = Field(
        "async", description="async returns 202 immediately; sync blocks until done"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "dag_id": "data_quality_pipeline",
                "incremental": True,
                "skip_reporting": False,
                "mode": "async",
            }
        }
    }


class BackfillRequest(BaseModel):
    """Body for ``POST /api/pipeline/backfill``."""

    start_date: date = Field(..., description="First partition date (inclusive)")
    end_date: date = Field(..., description="Last partition date (inclusive)")
    dag_id: DagId = Field("daily_etl_pipeline")
    incremental: bool = Field(False, description="Backfills normally replay full snapshots")

    @field_validator("start_date", "end_date")
    @classmethod
    def _not_in_the_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("backfill dates cannot be in the future")
        if value < date(2023, 1, 1):
            raise ValueError("backfill dates cannot precede the history start (2023-01-01)")
        return value

    @model_validator(mode="after")
    def _window(self) -> "BackfillRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days > 31:
            raise ValueError("backfill window is limited to 31 days per request")
        return self


# ------------------------------------------------------------------ responses
class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    database: dict[str, Any]
    warehouse: dict[str, int]
    latest_run: dict[str, Any] | None = None
    generated_at: datetime


class OverviewResponse(BaseModel):
    generated_at: datetime
    kpis: dict[str, Any]
    revenue_trend: list[dict[str, Any]]
    monthly_revenue: list[dict[str, Any]]
    top_categories: list[dict[str, Any]]
    channel_mix: list[dict[str, Any]]
    recent_runs: list[dict[str, Any]]
    quality: dict[str, Any]
    pipeline: dict[str, Any]


class SalesAnalyticsResponse(BaseModel):
    summary: dict[str, Any]
    daily: list[dict[str, Any]]
    monthly: list[dict[str, Any]]
    by_category: list[dict[str, Any]]
    by_region: list[dict[str, Any]]
    by_channel: list[dict[str, Any]]
    top_products: list[dict[str, Any]]
    discount_impact: list[dict[str, Any]]
    payment_methods: list[dict[str, Any]]
    forecast: list[dict[str, Any]]


class CustomerAnalyticsResponse(BaseModel):
    summary: dict[str, Any]
    new_vs_returning: list[dict[str, Any]]
    rfm_segments: list[dict[str, Any]]
    top_customers: dict[str, Any]
    retention: list[dict[str, Any]]
    clv_distribution: list[dict[str, Any]]


class ProductAnalyticsResponse(BaseModel):
    summary: dict[str, Any]
    products: dict[str, Any]
    by_category: list[dict[str, Any]]
    best_sellers: list[dict[str, Any]]
    worst_return_rates: list[dict[str, Any]]


class OrderExplorerResponse(BaseModel):
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int
    pages: int
    filters: dict[str, Any]
    summary: dict[str, Any]


class PipelineStatusResponse(BaseModel):
    status: str
    active_run: dict[str, Any] | None
    latest_run: dict[str, Any] | None
    stages: list[dict[str, Any]]
    health: dict[str, Any]
    freshness: list[dict[str, Any]]
    watermarks: list[dict[str, Any]]
    success_rate_pct: float | None


class PipelineHistoryResponse(BaseModel):
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int
    pages: int
    tasks: list[dict[str, Any]] = []


class DataQualityResponse(BaseModel):
    score: float | None
    summary: dict[str, Any]
    checks: list[dict[str, Any]]
    history: list[dict[str, Any]]
    quarantine: dict[str, Any]
    quarantine_reasons: list[dict[str, Any]]


class ReportsResponse(BaseModel):
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int
    pages: int


class TriggerAcceptedResponse(BaseModel):
    run_id: int | None
    dag_id: str
    status: str
    mode: str
    started_at: datetime
    message: str


class BackfillResponse(BaseModel):
    dag_id: str
    start_date: date
    end_date: date
    partitions: int
    run_id: int | None
    status: str
    coverage: list[dict[str, Any]]
    message: str
