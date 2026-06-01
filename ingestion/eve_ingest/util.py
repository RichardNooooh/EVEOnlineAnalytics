import os
from collections.abc import Iterable
from datetime import date, timedelta

DEFAULT_DATA_ROOT = "/opt/eve-market/data"
DEFAULT_RAW_ROOT = f"{DEFAULT_DATA_ROOT}/raw"
DEFAULT_DUCKLAKE_RAW_DATA_PATH = f"{DEFAULT_DATA_ROOT}/datasets/ducklake/raw"
DEFAULT_DUCKLAKE_CATALOG = os.environ.get(
    "EVE_DUCKLAKE_CATALOG",
    "postgresql://airflow:airflow-local-only@postgres:5432/airflow",
)
DEFAULT_DUCKLAKE_LOCK_WAIT_TIMEOUT_SECONDS = float(os.environ.get("EVE_DUCKLAKE_LOCK_WAIT_TIMEOUT_SECONDS", "60"))
DEFAULT_RAW_LEDGER_URL = os.environ.get(
    "EVE_RAW_LEDGER_URL",
    "postgresql://raw_files:password@postgres:5432/raw_files",
)
DEFAULT_DUCKLAKE_METADATA_SCHEMA = "eve_market"


def parse_iso_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid YYYY-MM-DD date") from exc


def file_size(path: str) -> int | None:
    """Return file size in bytes, or None if the file is inaccessible."""
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def iter_dates(start: date, end: date) -> Iterable[date]:
    """Yield each date in ``[start, end]`` inclusive."""
    for n in range((end - start).days + 1):
        yield start + timedelta(n)
