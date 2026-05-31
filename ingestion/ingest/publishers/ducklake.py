from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qsl, unquote, urlparse
from uuid import uuid4

import duckdb
import pyarrow as pa

from ingest.util import (
    DEFAULT_DUCKLAKE_CATALOG,
    DEFAULT_DUCKLAKE_METADATA_SCHEMA,
    DEFAULT_DUCKLAKE_RAW_DATA_PATH,
)

logger = logging.getLogger("ingest.publishers")

DEFAULT_DUCKLAKE_ALIAS = "ducklake"
DEFAULT_RAW_SCHEMA = "raw"

_IDENTIFIER_RE = re.compile(r"^[^\s-]+$")


@dataclass(frozen=True)
class DuckLakeAttachConfig:
    """Resolved DuckLake attachment settings for one writable target."""

    attach_uri: str
    data_path: str
    metadata_schema: str = "main"
    alias: str = DEFAULT_DUCKLAKE_ALIAS
    override_data_path: bool = True


@dataclass(frozen=True)
class DuckLakeTableTarget:
    """Logical schema and table name inside attached DuckLake alias."""

    schema: str
    table: str


class RawDuckLakeTable(StrEnum):
    MARKET_HISTORY = "raw_market_history"
    MARKET_ORDERS = "raw_market_orders"
    FUZZWORK_ORDERS = "raw_fuzzwork_orders"
    REFERENCE_CATEGORIES = "raw_reference_categories"
    REFERENCE_GROUPS = "raw_reference_groups"
    REFERENCE_REGIONS = "raw_reference_regions"
    REFERENCE_TYPES = "raw_reference_types"


class DuckLakeWriterMode(StrEnum):
    INSERT_MISSING_KEYS = "insert_missing_keys"
    ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS = "assert_partition_coverage_insert_missing_keys"
    REPLACE_TABLE = "replace_table"


def build_ducklake_attach_config_from_url(
    postgres_url: str,
    *,
    data_path: str | None = None,
    metadata_schema: str | None = None,
    alias: str | None = None,
) -> DuckLakeAttachConfig:
    """Build a DuckLakeAttachConfig from an arbitrary PostgreSQL URL.

    Args:
        postgres_url: PostgreSQL URL for the DuckLake catalog.
        data_path: Override the default raw data path.
        metadata_schema: Override the default metadata schema.
        alias: Override the default alias.
    """
    parsed = urlparse(postgres_url)
    scheme = parsed.scheme.split("+")[0]
    if scheme not in {"postgres", "postgresql"}:
        raise ValueError("ducklake_catalog must be a PostgreSQL URL")
    if not parsed.hostname:
        raise ValueError("ducklake_catalog must include a host")
    if parsed.path in {"", "/"}:
        raise ValueError("ducklake_catalog must include a database name")

    parts = [f"dbname={parsed.path.removeprefix('/')}", f"host={parsed.hostname}"]
    if parsed.port is not None:
        parts.append(f"port={parsed.port}")
    if parsed.username is not None:
        parts.append(f"user={unquote(parsed.username)}")
    if parsed.password is not None:
        parts.append(f"password={unquote(parsed.password)}")

    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        parts.append(f"{key}={value}")

    return DuckLakeAttachConfig(
        attach_uri="ducklake:postgres:" + " ".join(parts),
        data_path=data_path or DEFAULT_DUCKLAKE_RAW_DATA_PATH,
        metadata_schema=metadata_schema or DEFAULT_DUCKLAKE_METADATA_SCHEMA,
        alias=alias or DEFAULT_DUCKLAKE_ALIAS,
    )


def _build_default_attach_config() -> DuckLakeAttachConfig:
    return build_ducklake_attach_config_from_url(DEFAULT_DUCKLAKE_CATALOG)


def _quote_identifier(identifier: str) -> str:
    if not identifier or _IDENTIFIER_RE.fullmatch(identifier) is None:
        raise ValueError("SQL identifiers must be non-empty strings without spaces or dashes")
    return '"' + identifier.replace('"', '""') + '"'


def _quote_table_target(alias: str, target: DuckLakeTableTarget) -> str:
    return ".".join(
        [
            _quote_identifier(alias),
            _quote_identifier(target.schema),
            _quote_identifier(target.table),
        ]
    )


def _build_key_columns_clause(key_columns: Sequence[str]) -> str:
    if not key_columns:
        raise ValueError("key_columns must not be empty when writer mode requires keys")
    return ", ".join(_quote_identifier(key) for key in key_columns)


def _target_for(table: RawDuckLakeTable) -> DuckLakeTableTarget:
    return DuckLakeTableTarget(schema=DEFAULT_RAW_SCHEMA, table=table.value)


@contextmanager
def _temporary_arrow_view(con: duckdb.DuckDBPyConnection, arrow_table: pa.Table) -> Iterator[str]:
    source_name = f"_arrow_source_{uuid4().hex}"
    con.from_arrow(arrow_table).create_view(source_name)
    try:
        yield source_name
    finally:
        con.execute(f"DROP VIEW IF EXISTS {_quote_identifier(source_name)}")


def _quote_literal(value: str) -> str:
    """Quote a string as a SQL literal (single-quoted, escaped)."""
    return "'" + value.replace("'", "''") + "'"


def _attach_ducklake(
    con: duckdb.DuckDBPyConnection,
    *,
    config: DuckLakeAttachConfig,
) -> None:
    """Load DuckLake extensions and attach target lake into connection."""

    if config.attach_uri.startswith("ducklake:postgres:"):
        con.execute("INSTALL postgres")
        con.execute("LOAD postgres")
    con.execute("INSTALL ducklake")
    con.execute("LOAD ducklake")
    con.execute(
        f"""
        ATTACH {_quote_literal(config.attach_uri)} AS {_quote_identifier(config.alias)} (
            DATA_PATH {_quote_literal(config.data_path)},
            METADATA_SCHEMA {_quote_literal(config.metadata_schema)},
            OVERRIDE_DATA_PATH {"TRUE" if config.override_data_path else "FALSE"}
        )
        """
    )


def _assert_matched_key_rows_identical(
    con: duckdb.DuckDBPyConnection,
    arrow_table: pa.Table,
    *,
    quoted_target: str,
    quoted_source: str,
    key_columns: Sequence[str],
) -> None:
    """Raise when matched keys have differing non-key values.

    Uses a SQL JOIN with IS DISTINCT FROM to detect differences efficiently
    without materialising full tables in Python.
    """
    non_key_cols = [col for col in arrow_table.column_names if col not in key_columns and not col.startswith("_")]
    if not non_key_cols:
        return

    key_join = " AND ".join(f"s.{_quote_identifier(k)} = t.{_quote_identifier(k)}" for k in key_columns)
    key_list = ", ".join(f"s.{_quote_identifier(k)}" for k in key_columns)
    where_clause = " OR ".join(
        f"s.{_quote_identifier(c)} IS DISTINCT FROM t.{_quote_identifier(c)}" for c in non_key_cols
    )
    query = f"""
        SELECT {key_list}
        FROM {quoted_source} s
        JOIN {quoted_target} t ON {key_join}
        WHERE {where_clause}
    """
    try:
        differing = con.execute(query).fetchall()
    except Exception:
        raise ValueError("Could not query target for key validation")

    if differing:
        examples = ", ".join(
            ", ".join(f"{key}={value!r}" for key, value in zip(key_columns, row)) for row in differing[:10]
        )
        raise ValueError(f"Matched key rows have differing values: {examples}")


def _assert_target_rows_missing_from_source(
    con: duckdb.DuckDBPyConnection,
    arrow_table: pa.Table,
    *,
    quoted_target: str,
    quoted_source: str,
    key_columns: Sequence[str],
) -> None:
    source_date_col = "_source_market_date"
    if source_date_col not in arrow_table.column_names:
        return

    key_join = " AND ".join(f"s.{_quote_identifier(k)} = t.{_quote_identifier(k)}" for k in key_columns)
    key_list = ", ".join(f"t.{_quote_identifier(k)}" for k in key_columns)

    query = f"""
        WITH source_dates AS (
            SELECT DISTINCT {quoted_source}.{_quote_identifier(source_date_col)} AS source_date
            FROM {quoted_source}
        )
        SELECT t.{_quote_identifier(source_date_col)} AS source_date, {key_list}
        FROM {quoted_target} t
        JOIN source_dates sd
            ON t.{_quote_identifier(source_date_col)} = sd.source_date
        WHERE NOT EXISTS (
            SELECT 1
            FROM {quoted_source} s
            WHERE s.{_quote_identifier(source_date_col)} = t.{_quote_identifier(source_date_col)}
                AND {key_join}
        )
    """

    try:
        missing = con.execute(query).fetchall()
    except Exception as exc:
        raise ValueError("Could not query target for source-date coverage check") from exc

    if missing:
        examples = ", ".join(
            f"source_date={row[0]!r}, keys={dict(zip(key_columns, row[1:]))!r}" for row in missing[:10]
        )
        raise ValueError(f"Target has rows for source_date(s) absent from the newly downloaded source file: {examples}")


def _validate_key_columns(arrow_table: pa.Table, key_columns: Sequence[str]) -> None:
    if not key_columns:
        raise ValueError("key_columns must not be empty when writer mode requires keys")

    missing_key_columns = [key for key in key_columns if key not in arrow_table.column_names]
    if missing_key_columns:
        raise ValueError("key_columns must exist in arrow_table columns: " + ", ".join(missing_key_columns))


def _validate_replace_table_arguments(key_columns: Sequence[str]) -> None:
    if key_columns:
        raise ValueError("REPLACE_TABLE does not accept key_columns")


class DuckLakeWriter:
    """Context-managed writer for raw DuckLake tables.

    Example:
        ```python
        import pyarrow as pa
        from ingest.publishers.ducklake import DuckLakeWriter, DuckLakeWriterMode, RawDuckLakeTable

        rows = pa.table({"type_id": [34], "date": ["2026-01-01"]})
        with DuckLakeWriter() as writer:
            writer.write(rows, table=RawDuckLakeTable.MARKET_HISTORY, mode=DuckLakeWriterMode.REPLACE_TABLE)
        ```

    Example with explicit attach config:
        ```python
        config = DuckLakeAttachConfig(
            attach_uri="ducklake:postgres:dbname=airflow host=postgres",
            data_path="/opt/eve-market/data/datasets/ducklake/raw",
            metadata_schema="eve_market",
        )
        with DuckLakeWriter(config) as writer:
            writer.write(
                rows,
                table=RawDuckLakeTable.MARKET_ORDERS,
                mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
                key_columns=["order_id"],
            )
        ```
    """

    def __init__(self, config: DuckLakeAttachConfig | None = None) -> None:
        """Create a writer for the default or provided DuckLake target.

        Example:
            ```python
            writer = DuckLakeWriter()
            custom_writer = DuckLakeWriter(DuckLakeAttachConfig(...))
            ```
        """

        self._attach = config or _build_default_attach_config()
        self._con: duckdb.DuckDBPyConnection | None = None

    def __enter__(self) -> DuckLakeWriter:
        self._con = duckdb.connect()
        _attach_ducklake(self._con, config=self._attach)
        schema_name = f"{_quote_identifier(self._attach.alias)}.{_quote_identifier(DEFAULT_RAW_SCHEMA)}"
        self._con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
        logger.info(
            "DuckLake writer attached alias=%s metadata_schema=%s data_path=%s raw_schema=%s",
            self._attach.alias,
            self._attach.metadata_schema,
            self._attach.data_path,
            DEFAULT_RAW_SCHEMA,
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._con is None:
            return
        self._con.close()
        self._con = None

    def write(
        self,
        arrow_table: pa.Table,
        *,
        table: RawDuckLakeTable,
        mode: DuckLakeWriterMode,
        key_columns: Sequence[str] = (),
    ) -> None:
        """Write rows to a raw DuckLake table.

        `INSERT_MISSING_KEYS` inserts only previously unseen keys after asserting matched
        rows are identical. `ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS` adds the
        current market-history source-date coverage assertion. `REPLACE_TABLE` replaces
        the whole target table from the incoming Arrow table.

        Example:
            ```python
            writer.write(
                arrow_table,
                mode=DuckLakeWriterMode.REPLACE_TABLE,
                table=RawDuckLakeTable.MARKET_HISTORY,
            )
            writer.write(
                arrow_table,
                table=RawDuckLakeTable.MARKET_ORDERS,
                mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
                key_columns=["order_id"],
            )
            ```
        """

        con = self._con
        if con is None:
            raise RuntimeError("Missing DB connection. DuckLakeWriter must be used inside a with block")

        logger.debug(
            "Writing to DuckLake table=%s rows=%d columns=%d key_columns=%s mode=%s",
            table.value,
            len(arrow_table),
            len(arrow_table.column_names),
            list(key_columns),
            mode.value,
        )

        quoted_target = _quote_table_target(self._attach.alias, _target_for(table))

        if mode is DuckLakeWriterMode.REPLACE_TABLE and len(arrow_table) == 0:
            raise ValueError("REPLACE_TABLE requires a non-empty arrow_table")

        with _temporary_arrow_view(con, arrow_table) as source_name:
            quoted_source = _quote_identifier(source_name)
            if mode is DuckLakeWriterMode.REPLACE_TABLE:
                _validate_replace_table_arguments(key_columns)
                con.execute(
                    f"""
                    CREATE OR REPLACE TABLE {quoted_target} AS
                    SELECT * FROM {quoted_source}
                    """
                )
                logger.debug(
                    "DuckLake write complete table=%s attempted_rows=%d key_columns=%s",
                    table.value,
                    len(arrow_table),
                    list(key_columns),
                )
                return

            _validate_key_columns(arrow_table, key_columns)
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {quoted_target} AS
                SELECT * FROM {quoted_source} WHERE FALSE
                """
            )
            if mode in {
                DuckLakeWriterMode.INSERT_MISSING_KEYS,
                DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            }:
                _assert_matched_key_rows_identical(
                    con,
                    arrow_table,
                    quoted_target=quoted_target,
                    quoted_source=quoted_source,
                    key_columns=key_columns,
                )
                if mode is DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS:
                    _assert_target_rows_missing_from_source(
                        con,
                        arrow_table,
                        quoted_target=quoted_target,
                        quoted_source=quoted_source,
                        key_columns=key_columns,
                    )

                # DuckDB MERGE USING (columns) is an equi-join shorthand replacing ON.
                # Insert-only semantics are intentional (key_columns replaces merge_keys):
                # matched rows carry identical data (Everef sources), so WHEN MATCHED
                # THEN UPDATE would be a no-op write.
                con.execute(
                    f"""
                    MERGE INTO {quoted_target} AS target
                    USING {quoted_source} AS source
                    USING ({_build_key_columns_clause(key_columns)})
                    WHEN NOT MATCHED THEN INSERT BY NAME
                    """
                )
                logger.debug(
                    "DuckLake write complete table=%s attempted_rows=%d key_columns=%s",
                    table.value,
                    len(arrow_table),
                    list(key_columns),
                )
                return

            raise ValueError(f"Unsupported DuckLake writer mode: {mode}")
