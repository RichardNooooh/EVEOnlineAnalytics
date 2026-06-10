from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import duckdb
import pyarrow as pa

from eve_ingest.ducklake.raw_tables import DuckLakeTableTarget

logger = logging.getLogger("eve_ingest.ducklake")

_IDENTIFIER_RE = re.compile(r"^[^\s-]+$")


def datetime_now_utc() -> datetime:
    return datetime.now(UTC)


def quote_identifier(identifier: str) -> str:
    if not identifier or _IDENTIFIER_RE.fullmatch(identifier) is None:
        raise ValueError("SQL identifiers must be non-empty strings without spaces or dashes")
    return '"' + identifier.replace('"', '""') + '"'


def quote_sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def table_sql(alias: str, target: DuckLakeTableTarget) -> str:
    return ".".join(
        [
            quote_identifier(alias),
            quote_identifier(target.schema),
            quote_identifier(target.table),
        ]
    )


@contextmanager
def arrow_view(con: duckdb.DuckDBPyConnection, arrow_table: pa.Table) -> Iterator[str]:
    source_name = f"_arrow_source_{uuid4().hex}"
    con.from_arrow(arrow_table).create_view(source_name)
    try:
        yield source_name
    finally:
        con.execute(f"DROP VIEW IF EXISTS {quote_identifier(source_name)}")


@dataclass(frozen=True)
class SqlSource:
    sql: str


def count_source_rows_with_matches(
    con: duckdb.DuckDBPyConnection,
    *,
    quoted_target: str,
    quoted_source: str,
    key_columns: list[str],
) -> int:
    conditions = " AND ".join(f"target.{quote_identifier(key)} = source.{quote_identifier(key)}" for key in key_columns)
    row = con.execute(
        f"""
        SELECT COUNT(*)
        FROM {quoted_source} AS source
        WHERE EXISTS (
            SELECT 1
            FROM {quoted_target} AS target
            WHERE {conditions}
        )
        """
    ).fetchone()
    return int(row[0])


def count_source_rows_without_matches(
    con: duckdb.DuckDBPyConnection,
    *,
    quoted_target: str,
    quoted_source: str,
    key_columns: list[str],
) -> int:
    conditions = " AND ".join(f"target.{quote_identifier(key)} = source.{quote_identifier(key)}" for key in key_columns)
    row = con.execute(
        f"""
        SELECT COUNT(*)
        FROM {quoted_source} AS source
        WHERE NOT EXISTS (
            SELECT 1
            FROM {quoted_target} AS target
            WHERE {conditions}
        )
        """
    ).fetchone()
    return int(row[0])
