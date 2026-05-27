from __future__ import annotations

import re
from collections.abc import Sequence
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


def _build_default_attach_config() -> DuckLakeAttachConfig:
    parsed = urlparse(DEFAULT_DUCKLAKE_CATALOG)
    if parsed.scheme not in {"postgres", "postgresql"}:
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
        data_path=DEFAULT_DUCKLAKE_RAW_DATA_PATH,
        metadata_schema=DEFAULT_DUCKLAKE_METADATA_SCHEMA,
        alias=DEFAULT_DUCKLAKE_ALIAS,
    )


def _quote_identifier(identifier: str) -> str:
    if not identifier or _IDENTIFIER_RE.fullmatch(identifier) is None:
        raise ValueError(
            "SQL identifiers must be non-empty strings without spaces or dashes"
        )
    return '"' + identifier.replace('"', '""') + '"'


def _quote_table_target(alias: str, target: DuckLakeTableTarget) -> str:
    return ".".join(
        [
            _quote_identifier(alias),
            _quote_identifier(target.schema),
            _quote_identifier(target.table),
        ]
    )


def _build_merge_keys_clause(merge_keys: Sequence[str]) -> str:
    if not merge_keys:
        raise ValueError(
            "merge_keys must not be empty when merge behavior is requested"
        )
    return ", ".join(_quote_identifier(key) for key in merge_keys)


def _target_for(table: RawDuckLakeTable) -> DuckLakeTableTarget:
    return DuckLakeTableTarget(schema=DEFAULT_RAW_SCHEMA, table=table.value)


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
        ATTACH ? AS {_quote_identifier(config.alias)} (
            DATA_PATH ?,
            METADATA_SCHEMA ?,
            OVERRIDE_DATA_PATH {"TRUE" if config.override_data_path else "FALSE"}
        )
        """,
        [
            config.attach_uri,
            config.data_path,
            config.metadata_schema,
        ],
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
            writer.write(rows, table=RawDuckLakeTable.MARKET_ORDERS, merge_keys=["order_id"])
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
        merge_keys: Sequence[str] = (),
    ) -> None:
        """Write rows to a raw DuckLake table.

        Without `merge_keys`, rows append by column name. With `merge_keys`, rows are
        inserted only when no target row already matches those keys.

        Example:
            ```python
            writer.write(arrow_table, table=RawDuckLakeTable.MARKET_HISTORY)
            writer.write(
                arrow_table,
                table=RawDuckLakeTable.MARKET_ORDERS,
                merge_keys=["order_id"],
            )
            ```
        """

        con = self._con
        if con is None:
            raise RuntimeError(
                "Missing DB connection. DuckLakeWriter must be used inside a with block"
            )

        missing_merge_keys = [
            key for key in merge_keys if key not in arrow_table.column_names
        ]
        if missing_merge_keys:
            raise ValueError(
                "merge_keys must exist in arrow_table columns: "
                + ", ".join(missing_merge_keys)
            )

        source_name = f"_arrow_source_{uuid4().hex}"
        source_relation = con.from_arrow(arrow_table)
        source_relation.create_view(source_name)

        quoted_target = _quote_table_target(self._attach.alias, _target_for(table))
        quoted_source = _quote_identifier(source_name)

        try:
            if merge_keys:
                con.execute(
                    f"""
                    MERGE INTO {quoted_target} AS target
                    USING {quoted_source} AS source
                    USING ({_build_merge_keys_clause(merge_keys)})
                    WHEN NOT MATCHED THEN INSERT BY NAME
                    """
                )
                return

            con.execute(
                f"""
                INSERT INTO {quoted_target} BY NAME
                SELECT *
                FROM {quoted_source}
                """
            )
        finally:
            con.execute(f"DROP VIEW IF EXISTS {_quote_identifier(source_name)}")


def publish_arrow_table(
    *,
    arrow_table: pa.Table,
    table: RawDuckLakeTable,
    merge_keys: Sequence[str] = (),
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
            merge_keys=["order_id"],
        )
        ```
    """

    with DuckLakeWriter() as writer:
        writer.write(arrow_table, table=table, merge_keys=merge_keys)
