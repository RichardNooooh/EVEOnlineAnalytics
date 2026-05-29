from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qsl, unquote, urlparse
from uuid import uuid4

import duckdb
import pyarrow as pa

from ingest.publishers.logger import logger
from ingest.util import (
    DEFAULT_DUCKLAKE_CATALOG,
    DEFAULT_DUCKLAKE_METADATA_SCHEMA,
    DEFAULT_DUCKLAKE_RAW_DATA_PATH,
)

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
        raise ValueError("key_columns must not be empty when merge behavior is requested")
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


class DuckLakeWriter:
    """Context-managed writer for raw DuckLake tables.

    Example:
        ```python
        import pyarrow as pa
        from ingest.publishers.ducklake import DuckLakeWriter, RawDuckLakeTable

        rows = pa.table({"type_id": [34], "date": ["2026-01-01"]})
        with DuckLakeWriter() as writer:
            writer.write(rows, table=RawDuckLakeTable.MARKET_HISTORY)
        ```

    Example with explicit attach config:
        ```python
        config = DuckLakeAttachConfig(
            attach_uri="ducklake:postgres:dbname=airflow host=postgres",
            data_path="/opt/eve-market/data/datasets/ducklake/raw",
            metadata_schema="eve_market",
        )
        with DuckLakeWriter(config) as writer:
            writer.write(rows, table=RawDuckLakeTable.MARKET_ORDERS, key_columns=["order_id"])
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
        key_columns: Sequence[str] = (),
    ) -> None:
        """Write rows to a raw DuckLake table.

        Without `key_columns`, rows append by column name. With `key_columns`, rows are
        inserted only when no target row already matches those keys.

        Example:
            ```python
            writer.write(arrow_table, table=RawDuckLakeTable.MARKET_HISTORY)
            writer.write(
                arrow_table,
                table=RawDuckLakeTable.MARKET_ORDERS,
                key_columns=["order_id"],
            )
            ```
        """

        con = self._con
        if con is None:
            raise RuntimeError("Missing DB connection. DuckLakeWriter must be used inside a with block")

        missing_key_columns = [key for key in key_columns if key not in arrow_table.column_names]
        if missing_key_columns:
            raise ValueError("key_columns must exist in arrow_table columns: " + ", ".join(missing_key_columns))

        logger.debug(
            "Writing to DuckLake table=%s rows=%d columns=%d key_columns=%s mode=%s",
            table.value,
            len(arrow_table),
            len(arrow_table.column_names),
            list(key_columns),
            "merge" if key_columns else "append",
        )

        quoted_target = _quote_table_target(self._attach.alias, _target_for(table))
        with _temporary_arrow_view(con, arrow_table) as source_name:
            quoted_source = _quote_identifier(source_name)
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {quoted_target} AS
                SELECT * FROM {quoted_source} WHERE FALSE
                """
            )
            if key_columns:
                non_key_cols = [col for col in arrow_table.column_names if col not in key_columns]
                if non_key_cols:
                    key_clause = ", ".join(_quote_identifier(k) for k in key_columns)
                    subquery_cols = ", ".join(f"source.{_quote_identifier(k)}" for k in key_columns)
                    subquery = f"SELECT {subquery_cols} FROM {quoted_source}"
                    match_query = f"SELECT target.* FROM {quoted_target} AS target WHERE ({key_clause}) IN ({subquery})"
                    try:
                        matched_rows = con.execute(match_query).fetchall()
                        target_col_names = [desc[0] for desc in con.description]
                        if matched_rows:
                            source_rows = arrow_table.to_pylist()
                            for target_row in matched_rows:
                                target_dict = dict(zip(target_col_names, target_row))
                                key_values = {k: target_dict[k] for k in key_columns}
                                for src_row in source_rows:
                                    if all(src_row.get(k) == target_dict[k] for k in key_columns):
                                        diffs = {}
                                        for col in non_key_cols:
                                            if col in target_dict and col in src_row:
                                                if src_row[col] != target_dict[col]:
                                                    diffs[col] = (target_dict[col], src_row[col])
                                        if diffs:
                                            logger.warning(
                                                "Matched key %s has differing values; inserting new row "
                                                "(latest everef is always right). Diffs: %s",
                                                key_values,
                                                {c: {"old": o, "new": n} for c, (o, n) in diffs.items()},
                                            )
                                        break
                    except Exception:
                        logger.warning("Could not query target for key validation", exc_info=True)

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

            con.execute(
                f"""
                INSERT INTO {quoted_target} BY NAME
                SELECT *
                FROM {quoted_source}
                """
            )
            logger.debug(
                "DuckLake write complete table=%s attempted_rows=%d key_columns=%s",
                table.value,
                len(arrow_table),
                list(key_columns),
            )


def publish_arrow_table(
    *,
    arrow_table: pa.Table,
    table: RawDuckLakeTable,
    key_columns: Sequence[str] = (),
) -> None:
    """Write Arrow rows to the default raw DuckLake target.

    This is the one-shot helper for callers that do not need to reuse a writer.

    Example:
        ```python
        publish_arrow_table(
            arrow_table=rows,
            table=RawDuckLakeTable.MARKET_HISTORY,
        )
        publish_arrow_table(
            arrow_table=orders,
            table=RawDuckLakeTable.MARKET_ORDERS,
            key_columns=["order_id"],
        )
        ```
    """

    with DuckLakeWriter() as writer:
        writer.write(arrow_table, table=table, key_columns=key_columns)
