from collections.abc import Iterable
from datetime import date, timedelta

DEFAULT_DATA_ROOT = "/opt/eve-market/data"
DEFAULT_RAW_ROOT = f"{DEFAULT_DATA_ROOT}/raw"
DEFAULT_DUCKLAKE_RAW_DATA_PATH = f"{DEFAULT_DATA_ROOT}/datasets/ducklake/raw"
DEFAULT_DUCKLAKE_CATALOG = "postgresql://airflow:airflow-local-only@postgres:5432/airflow"
DEFAULT_RAW_LEDGER_URL = "postgresql://raw_files:password@postgres:5432/raw_files"
DEFAULT_DUCKLAKE_METADATA_SCHEMA = "eve_market"


def parse_iso_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid YYYY-MM-DD date") from exc


def iter_dates(start: date, end: date) -> Iterable[date]:
    """Yield each date in ``[start, end]`` inclusive."""
    for n in range((end - start).days + 1):
        yield start + timedelta(n)
