from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re
from uuid import uuid4
from urllib.parse import parse_qsl, unquote, urlparse

import duckdb
import pyarrow as pa

DEFAULT_DUCKLAKE_ALIAS = "ducklake"

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


def build_ducklake_attach_path(ducklake_catalog: str) -> str:
    """Convert PostgreSQL catalog URL into DuckLake attach URI."""

    parsed = urlparse(ducklake_catalog)
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

    return "ducklake:postgres:" + " ".join(parts)


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


def attach_ducklake(
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


def write_arrow_table(
    con: duckdb.DuckDBPyConnection,
    *,
    arrow_table: pa.Table,
    attach: DuckLakeAttachConfig,
    target: DuckLakeTableTarget,
    merge_keys: Sequence[str] = (),
) -> None:
    """Write Arrow rows to DuckLake target, appending or insert-merging by keys."""

    for merge_key in merge_keys:
        _quote_identifier(merge_key)

    missing_merge_keys = [
        key for key in merge_keys if key not in arrow_table.column_names
    ]
    if missing_merge_keys:
        raise ValueError(
            "merge_keys must exist in arrow_table columns: "
            + ", ".join(missing_merge_keys)
        )

    attach_ducklake(con, config=attach)

    source_name = f"_arrow_source_{uuid4().hex}"
    source_relation = con.from_arrow(arrow_table)
    source_relation.create_view(source_name)

    quoted_target = _quote_table_target(attach.alias, target)
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
