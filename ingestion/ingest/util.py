from datetime import date

DEFAULT_DATA_ROOT = "/opt/eve-market/data"
DEFAULT_DUCKLAKE_RAW_DATA_PATH = f"{DEFAULT_DATA_ROOT}/datasets/ducklake/raw"
DEFAULT_DUCKLAKE_CATALOG = (
    "postgresql://airflow:airflow-local-only@127.0.0.1:5432/airflow"
)
DEFAULT_DUCKLAKE_METADATA_SCHEMA = "eve_market"


def parse_iso_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid YYYY-MM-DD date") from exc
