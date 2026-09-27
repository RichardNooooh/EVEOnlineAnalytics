"""Read-only access to dbt's local analytical relations."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _repository_root() -> Path | None:
    configured_root = os.environ.get("EVE_MARKET_REPO_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()

    source_root = Path(__file__).resolve().parents[3]
    if (source_root / "infra" / "local").is_dir():
        return source_root

    for candidate in (Path.cwd(), *Path.cwd().parents):
        if (candidate / "infra" / "local").is_dir():
            return candidate

    return None


def _local_environment(repository_root: Path | None) -> dict[str, str]:
    if repository_root is None:
        return {}

    env_path = repository_root / "infra" / "local" / ".env"
    if not env_path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _setting(name: str, local_environment: Mapping[str, str], default: str) -> str:
    return os.environ.get(name, local_environment.get(name, default))


def _sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid DuckDB identifier: {value!r}")
    return value


@contextmanager
def open_analysis_connection() -> Iterator[duckdb.DuckDBPyConnection]:
    """Open dbt's scratch database and attach the raw DuckLake read-only."""
    repository_root = _repository_root()
    local_environment = _local_environment(repository_root)

    database_path = Path(
        _setting("DBT_DUCKDB_PATH", local_environment, "/tmp/eve_market_transform.duckdb")
    ).expanduser()
    if not database_path.is_file():
        raise FileNotFoundError(f"dbt work database not found at {database_path}. Run the transformation build first.")

    attach_uri = _setting("DBT_DUCKLAKE_ATTACH_PATH", local_environment, "")
    if not attach_uri:
        postgres_db = _setting("POSTGRES_DB", local_environment, "airflow")
        postgres_host = _setting("DBT_POSTGRES_HOST", local_environment, "127.0.0.1")
        postgres_port = _setting("POSTGRES_HOST_PORT", local_environment, "5432")
        postgres_user = _setting("POSTGRES_USER", local_environment, "airflow")
        postgres_password = _setting("POSTGRES_PASSWORD", local_environment, "airflow-local-only")
        attach_uri = (
            "ducklake:postgres:"
            f"dbname={postgres_db} host={postgres_host} port={postgres_port} "
            f"user={postgres_user} password={postgres_password}"
        )

    default_data_path = (
        repository_root / ".local" / "data" / "datasets" / "ducklake" / "raw"
        if repository_root is not None
        else Path("/app/ducklake/raw_market_history/files")
    )
    data_path = Path(_setting("DBT_DUCKLAKE_DATA_PATH", local_environment, str(default_data_path))).expanduser()
    if not data_path.is_absolute():
        if repository_root is None:
            raise ValueError("DBT_DUCKLAKE_DATA_PATH must be absolute outside a source checkout.")
        data_path = (repository_root / "transformation" / data_path).resolve()

    alias = _identifier(_setting("DBT_DUCKLAKE_ALIAS", local_environment, "raw_lake"))
    metadata_schema = _setting("DBT_DUCKLAKE_METADATA_SCHEMA", local_environment, "eve_market")
    override_data_path = _setting("DBT_DUCKLAKE_OVERRIDE_DATA_PATH", local_environment, "1")
    if override_data_path not in {"0", "1"}:
        raise ValueError("DBT_DUCKLAKE_OVERRIDE_DATA_PATH must be 0 or 1.")

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        connection.execute("load ducklake")
        connection.execute(
            f"""
            attach {_sql_string(attach_uri)} as {alias} (
                data_path {_sql_string(data_path)},
                metadata_schema {_sql_string(metadata_schema)},
                override_data_path {"true" if override_data_path == "1" else "false"},
                read_only
            )
            """
        )
        yield connection
    finally:
        connection.close()
