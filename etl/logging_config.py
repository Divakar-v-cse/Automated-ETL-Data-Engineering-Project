"""Structured JSON logging shared by the ETL jobs, the API and the scheduler."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from etl.config import LOG_DIR


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("run_id", "dag_id", "task", "stage", "records", "duration_s"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name: str = "etl", log_file: str = "pipeline.log") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(JsonFormatter())
    logger.addHandler(stream)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(Path(LOG_DIR) / log_file, encoding="utf-8")
    fh.setFormatter(JsonFormatter())
    logger.addHandler(fh)
    logger.propagate = False
    return logger
