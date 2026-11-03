"""Report listing, detail and download."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from backend.app.db import one, rows, scalar
from backend.app.schemas import ReportsResponse
from etl.config import REPORT_DIR

router = APIRouter(prefix="/api/reports", tags=["reports"])

LIST_COLUMNS = ("id, report_id, report_type, period_start, period_end, title, "
                "file_path, generated_at")


def _pages(total: int, size: int) -> int:
    return max(1, -(-total // size)) if total else 0


def _resolve(report: dict) -> Path:
    """Resolve a stored path inside the reports directory (no traversal)."""
    stored = report.get("file_path") or ""
    candidate = Path(stored)
    if not candidate.is_absolute():
        candidate = (Path(__file__).resolve().parents[3] / stored).resolve()
    else:
        candidate = candidate.resolve()
    root = Path(REPORT_DIR).resolve()
    if root not in candidate.parents and candidate.parent != root:
        raise HTTPException(status_code=400, detail="report path is outside the reports directory")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"report file missing: {candidate.name}")
    return candidate


@router.get("", response_model=ReportsResponse, summary="List generated reports")
def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    report_type: str | None = Query(None, pattern="^(daily|weekly)$"),
) -> ReportsResponse:
    where, params = ["1 = 1"], {}
    if report_type:
        where.append("report_type = :t")
        params["t"] = report_type
    clause = " AND ".join(where)
    total = int(scalar(f"SELECT COUNT(*) FROM reports WHERE {clause}", params) or 0)
    items = rows(
        f"SELECT {LIST_COLUMNS} FROM reports WHERE {clause} "
        f"ORDER BY generated_at DESC, id DESC LIMIT :limit OFFSET :offset",
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    )
    for item in items:
        summary_raw = scalar("SELECT summary_json FROM reports WHERE report_id = :r",
                             {"r": item["report_id"]})
        try:
            item["summary"] = json.loads(summary_raw) if summary_raw else None
        except (TypeError, ValueError):
            item["summary"] = None
    return ReportsResponse(items=items, page=page, page_size=page_size,
                           total=total, pages=_pages(total, page_size))


@router.get("/{report_id}", summary="Report detail with rendered content")
def report_detail(report_id: str) -> dict:
    report = one(f"SELECT {LIST_COLUMNS}, summary_json FROM reports "
                 f"WHERE report_id = :r", {"r": report_id})
    if not report:
        raise HTTPException(status_code=404, detail=f"report {report_id} not found")
    path = _resolve(report)
    content = None
    if path.suffix.lower() in {".md", ".txt", ".json"}:
        content = path.read_text(encoding="utf-8")[:200_000]
    try:
        summary = json.loads(report.get("summary_json") or "{}")
    except ValueError:
        summary = {}
    report.pop("summary_json", None)
    return {
        "report": report,
        "summary": summary,
        "content": content,
        "download_url": f"/api/reports/{report_id}/download",
        "media_type": {".html": "text/html", ".md": "text/markdown",
                       ".json": "application/json"}.get(path.suffix.lower(), "text/plain"),
    }


@router.get("/{report_id}/download", summary="Download the report artefact")
def download(report_id: str) -> FileResponse:
    report = one(f"SELECT {LIST_COLUMNS} FROM reports WHERE report_id = :r",
                 {"r": report_id})
    if not report:
        raise HTTPException(status_code=404, detail=f"report {report_id} not found")
    path = _resolve(report)
    media = {".html": "text/html", ".md": "text/markdown",
             ".json": "application/json"}.get(path.suffix.lower(), "text/plain")
    return FileResponse(path, media_type=media,
                        filename=f"{report['report_type']}_{report['period_end']}{path.suffix}")


@router.get("/{report_id}/html", response_class=HTMLResponse,
            summary="Render the HTML report inline")
def report_html(report_id: str) -> HTMLResponse:
    report = one(f"SELECT {LIST_COLUMNS} FROM reports WHERE report_id = :r",
                 {"r": report_id})
    if not report:
        raise HTTPException(status_code=404, detail=f"report {report_id} not found")
    html_path = Path(_resolve(report))
    if html_path.suffix.lower() != ".html":
        candidate = html_path.with_suffix(".html")
        if not candidate.exists():
            raise HTTPException(status_code=404, detail="no HTML artefact for this report")
        html_path = candidate
    return HTMLResponse(html_path.read_text(encoding="utf-8"))

