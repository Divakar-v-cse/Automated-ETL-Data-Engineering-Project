"""Extraction layer: CSV, JSON, REST API, and SQL sources."""
from etl.extract.api_extractor import extract_api
from etl.extract.csv_extractor import extract_csv
from etl.extract.db_extractor import ensure_source_table, extract_db
from etl.extract.json_extractor import extract_json_array, extract_jsonl

__all__ = [
    "extract_csv", "extract_jsonl", "extract_json_array", "extract_api",
    "extract_db", "ensure_source_table",
]
