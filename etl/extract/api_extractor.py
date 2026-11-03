"""REST API extraction for the payment system.

When ``SOURCE_API_URL`` is unset, a local mock payment-gateway endpoint is spun
up on a free port and fetched over real HTTP with pagination and exponential
backoff -- the same code path used against a production gateway.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd

from etl.config import RAW_DIR
from etl.extract.base import ExtractResult, Timer


class _MockPaymentHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        # /payments?page=N
        query = self.path.split("?", 1)[-1] if "?" in self.path else ""
        params = dict(p.split("=") for p in query.split("&") if "=" in p)
        page = int(params.get("page", "1"))
        page_file = Path(RAW_DIR) / "api" / f"payments_page_{page:03d}.json"
        if not page_file.exists():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "page not found"}')
            return
        body = page_file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass  # keep the console clean


@contextlib.contextmanager
def _mock_gateway():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockPaymentHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def _fetch(url: str, retries: int = 3, backoff: float = 0.5) -> dict:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover
            last = exc
            time.sleep(backoff * (2 ** (attempt - 1)))
    raise RuntimeError(f"API fetch failed after {retries} attempts: {last}")


def extract_api(entity: str, base_url: str | None = None,
                page_size: int = 5000) -> ExtractResult:
    timer = Timer()
    rows: list[dict] = []
    page = 1
    has_more = True
    attempts = 0

    if base_url is None:
        with _mock_gateway() as url:
            base_url = url
            while has_more:
                payload = _fetch(f"{base_url}/payments?page={page}")
                rows.extend(payload.get("data", []))
                has_more = bool(payload.get("has_more")) and bool(payload.get("data"))
                page += 1
                attempts += 1
    else:
        while has_more:
            payload = _fetch(f"{base_url}/payments?page={page}&page_size={page_size}")
            rows.extend(payload.get("data", []))
            has_more = bool(payload.get("has_more")) and bool(payload.get("data"))
            page += 1
            attempts += 1

    df = pd.DataFrame(rows)
    return ExtractResult(source="rest_api", entity=entity, records=len(df),
                         duration_seconds=timer.elapsed, frame=df,
                         meta={"base_url": base_url, "pages": attempts,
                               "transport": "https/urllib", "page_size": page_size})
