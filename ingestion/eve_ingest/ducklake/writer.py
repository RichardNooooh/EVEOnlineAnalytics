from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from uuid import uuid4

import duckdb
import pyarrow as pa

from eve_ingest.ducklake.attach_config import DEFAULT_RAW_SCHEMA, DuckLakeAttachConfig, _build_default_attach_config
from eve_ingest.ducklake.locks import DuckLakeLockToken, DuckLakeLockViolationError
from eve_ingest.ducklake.raw_tables import (
    DuckLakeTableTarget,
    DuckLakeWriteMetrics,
    DuckLakeWriterMode,
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
    _target_for,
    provenance_target_for,
    raw_table_column_definitions,
    source_object_column_definitions,
)

logger = logging.getLogger("eve_ingest.ducklake")

_IDENTIFIER_RE = re.compile(r"^[^\s-]+$")


############################
# SQL Helpers
############################


def _ident(identifier: str) -> str:
    if not identifier or _IDENTIFIER_RE.fullmatch(identifier) is None:
        raise ValueError("SQL identifiers must be non-empty strings without spaces or dashes")
    return '"' + identifier.replace('"', '""') + '"'


def _table_sql(alias: str, target: DuckLakeTableTarget) -> str:
    return ".".join(
        [
            _ident(alias),
            _ident(target.schema),
            _ident(target.table),
        ]
    )


@contextmanager
def _arrow_view(con: duckdb.DuckDBPyConnection, arrow_table: pa.Table) -> Iterator[str]:
    source_name = f"_arrow_source_{uuid4().hex}"
    con.from_arrow(arrow_table).create_view(source_name)
    try:
        yield source_name
    finally:
        con.execute(f"DROP VIEW IF EXISTS {_ident(source_name)}")


def _quote_literal(value: str) -> str:
    """Quote a string as a SQL literal (single-quoted, escaped)."""
    return "'" + value.replace("'", "''") + "'"


def _attach(
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
        ATTACH {_quote_literal(config.attach_uri)} AS {_ident(config.alias)} (
            DATA_PATH {_quote_literal(config.data_path)},
            METADATA_SCHEMA {_quote_literal(config.metadata_schema)},
            OVERRIDE_DATA_PATH {"TRUE" if config.override_data_path else "FALSE"}
        )
        """
    )


############################
# Validation Helpers
############################


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

    key_join = " AND ".join(f"s.{_ident(k)} = t.{_ident(k)}" for k in key_columns)
    key_list = ", ".join(f"s.{_ident(k)}" for k in key_columns)
    where_clause = " OR ".join(f"s.{_ident(c)} IS DISTINCT FROM t.{_ident(c)}" for c in non_key_cols)
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
    source_date_col = "source_market_date"
    if source_date_col not in arrow_table.column_names:
        return

    key_join = " AND ".join(f"s.{_ident(k)} = t.{_ident(k)}" for k in key_columns)
    key_list = ", ".join(f"t.{_ident(k)}" for k in key_columns)

    query = f"""
        WITH source_dates AS (
            SELECT DISTINCT {quoted_source}.{_ident(source_date_col)} AS source_date
            FROM {quoted_source}
        )
        SELECT t.{_ident(source_date_col)} AS source_date, {key_list}
        FROM {quoted_target} t
        JOIN source_dates sd
            ON t.{_ident(source_date_col)} = sd.source_date
        WHERE NOT EXISTS (
            SELECT 1
            FROM {quoted_source} s
            WHERE s.{_ident(source_date_col)} = t.{_ident(source_date_col)}
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

    for key in key_columns:
        _ident(key)

    missing_key_columns = [key for key in key_columns if key not in arrow_table.column_names]
    if missing_key_columns:
        raise ValueError("key_columns must exist in arrow_table columns: " + ", ".join(missing_key_columns))


def _target_exists(con: duckdb.DuckDBPyConnection, *, alias: str, target: DuckLakeTableTarget) -> bool:
    exists = con.execute(
        """
        SELECT COUNT(*)
        FROM duckdb_tables()
        WHERE database_name = ?
            AND schema_name = ?
            AND table_name = ?
        """,
        [alias, target.schema, target.table],
    ).fetchone()
    return bool(exists and exists[0])


def _require_table(
    con: duckdb.DuckDBPyConnection,
    *,
    alias: str,
    target: DuckLakeTableTarget,
) -> None:
    if _target_exists(con, alias=alias, target=target):
        return
    raise RuntimeError(
        f"Missing bootstrapped raw table {target.schema}.{target.table}. "
        "Run `eve-ingest ducklake bootstrap raw` before publication."
    )


############################
# Metric Helpers
############################


def _count_source_rows_with_matches(
    con: duckdb.DuckDBPyConnection,
    *,
    quoted_target: str,
    quoted_source: str,
    key_columns: Sequence[str],
) -> int:
    conditions = " AND ".join(f"target.{_ident(key)} = source.{_ident(key)}" for key in key_columns)
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


def _count_source_rows_without_matches(
    con: duckdb.DuckDBPyConnection,
    *,
    quoted_target: str,
    quoted_source: str,
    key_columns: Sequence[str],
) -> int:
    conditions = " AND ".join(f"target.{_ident(key)} = source.{_ident(key)}" for key in key_columns)
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


############################
# Writer
############################


class DuckLakeWriter:
    """Context-managed writer for raw DuckLake tables.

    Example:
        ```python
        import pyarrow as pa
        from eve_ingest.ducklake.writer import DuckLakeWriter, DuckLakeWriterMode, RawDuckLakeTable

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

    def __init__(
        self,
        config: DuckLakeAttachConfig | None = None,
        *,
        lock_token: DuckLakeLockToken | None = None,
        declared_mode: DuckLakeWriterMode | None = None,
        dataset_name: str | None = None,
    ) -> None:
        """Create a writer for the default or provided DuckLake target.

        `declared_mode`, when provided by a workflow publisher declaration, rejects
        accidental calls with a different write mode before any DuckDB mutation work.
        """

        self._attach = config or _build_default_attach_config()
        self._lock_token = lock_token
        self._declared_mode = declared_mode
        self._dataset_name = dataset_name
        self._con: duckdb.DuckDBPyConnection | None = None
        self._write_history: list[DuckLakeWriteMetrics] = []
        self._transaction_depth = 0

    def __enter__(self) -> DuckLakeWriter:
        self._con = duckdb.connect()
        _attach(self._con, config=self._attach)
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

    @property
    def write_history(self) -> tuple[DuckLakeWriteMetrics, ...]:
        return tuple(self._write_history)

    def write(
        self,
        arrow_table: pa.Table,
        *,
        table: RawDuckLakeTable,
        mode: DuckLakeWriterMode,
        key_columns: Sequence[str] = (),
    ) -> DuckLakeWriteMetrics:
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

        if self._declared_mode is not None and mode != self._declared_mode:
            requested_mode = getattr(mode, "value", str(mode))
            raise ValueError(
                "DuckLake writer mode does not match publisher declaration "
                f"dataset={self._dataset_name or '-'} table={table.value} "
                f"declared_mode={self._declared_mode.value} requested_mode={requested_mode}"
            )

        con = self._con
        if con is None:
            raise RuntimeError("Missing DB connection. DuckLakeWriter must be used inside a with block")
        self._require_data_table_lock(table)

        logger.debug(
            "Writing to DuckLake table=%s rows=%d columns=%d key_columns=%s mode=%s",
            table.value,
            len(arrow_table),
            len(arrow_table.column_names),
            list(key_columns),
            mode.value,
        )

        quoted_target = _table_sql(self._attach.alias, _target_for(table))
        target = _target_for(table)

        if mode is DuckLakeWriterMode.REPLACE_TABLE and len(arrow_table) == 0:
            raise ValueError("REPLACE_TABLE requires a non-empty arrow_table")

        with _arrow_view(con, arrow_table) as source_name:
            quoted_source = _ident(source_name)
            if mode is DuckLakeWriterMode.REPLACE_TABLE:
                if key_columns:
                    raise ValueError("REPLACE_TABLE does not accept key_columns")
                _require_table(
                    con,
                    alias=self._attach.alias,
                    target=target,
                )
                replaced_rows = int(con.execute(f"SELECT COUNT(*) FROM {quoted_target}").fetchone()[0])
                with self.transaction():
                    con.execute(f"DELETE FROM {quoted_target}")
                    con.execute(
                        f"""
                        INSERT INTO {quoted_target} BY NAME
                        SELECT * FROM {quoted_source}
                        """
                    )
                metrics = DuckLakeWriteMetrics(
                    table=table,
                    mode=mode,
                    attempted_rows=len(arrow_table),
                    inserted_rows=len(arrow_table),
                    matched_rows=0,
                    replaced_rows=replaced_rows,
                )
                self._write_history.append(metrics)
                logger.debug(
                    "DuckLake write complete table=%s mode=%s attempted_rows=%d inserted_rows=%d matched_rows=%d replaced_rows=%d key_columns=%s",
                    table.value,
                    mode.value,
                    metrics.attempted_rows,
                    metrics.inserted_rows,
                    metrics.matched_rows,
                    metrics.replaced_rows,
                    list(key_columns),
                )
                return metrics

            _validate_key_columns(arrow_table, key_columns)
            if mode in {
                DuckLakeWriterMode.INSERT_MISSING_KEYS,
                DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            }:
                _require_table(
                    con,
                    alias=self._attach.alias,
                    target=target,
                )
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

                matched_rows = _count_source_rows_with_matches(
                    con,
                    quoted_target=quoted_target,
                    quoted_source=quoted_source,
                    key_columns=key_columns,
                )
                inserted_rows = _count_source_rows_without_matches(
                    con,
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
                    USING ({", ".join(_ident(key) for key in key_columns)})
                    WHEN NOT MATCHED THEN INSERT BY NAME
                    """
                )
                metrics = DuckLakeWriteMetrics(
                    table=table,
                    mode=mode,
                    attempted_rows=len(arrow_table),
                    inserted_rows=inserted_rows,
                    matched_rows=matched_rows,
                    replaced_rows=0,
                )
                self._write_history.append(metrics)
                logger.debug(
                    "DuckLake write complete table=%s mode=%s attempted_rows=%d inserted_rows=%d matched_rows=%d replaced_rows=%d key_columns=%s",
                    table.value,
                    mode.value,
                    metrics.attempted_rows,
                    metrics.inserted_rows,
                    metrics.matched_rows,
                    metrics.replaced_rows,
                    list(key_columns),
                )
                return metrics

            raise ValueError(f"Unsupported DuckLake writer mode: {mode}")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        con = self._con
        if con is None:
            raise RuntimeError("Missing DB connection. DuckLakeWriter must be used inside a with block")

        outermost = self._transaction_depth == 0
        if outermost:
            con.execute("BEGIN")
        self._transaction_depth += 1
        try:
            yield
        except Exception:
            self._transaction_depth -= 1
            if outermost:
                self._transaction_depth = 0
                con.execute("ROLLBACK")
            raise
        else:
            self._transaction_depth -= 1
            if outermost:
                con.execute("COMMIT")

    def upsert_source_object(self, data: dict, *, table: RawDuckLakeProvenanceTable) -> None:
        con = self._con
        if con is None:
            raise RuntimeError("Missing DB connection. DuckLakeWriter must be used inside a with block")
        self._require_provenance_table_lock(table)

        quoted_target = _table_sql(self._attach.alias, provenance_target_for(table))

        columns = list(data.keys())
        col_list = ", ".join(_ident(c) for c in columns)
        select_list = ", ".join("?" for _ in columns)
        update_set = ", ".join(f"{_ident(k)} = source.{_ident(k)}" for k in columns if k != "source_object_id")
        insert_cols = ", ".join(f"source.{_ident(k)}" for k in columns)
        values = list(data.values())

        con.execute(
            f"""
            MERGE INTO {quoted_target} AS target
            USING (SELECT {select_list}) AS source({col_list})
            ON target.source_object_id = source.source_object_id
            WHEN MATCHED THEN UPDATE SET {update_set}
            WHEN NOT MATCHED THEN INSERT ({col_list}) VALUES ({insert_cols})
            """,
            values,
        )

    def _require_data_table_lock(self, table: RawDuckLakeTable) -> None:
        if self._lock_token is None:
            raise DuckLakeLockViolationError(
                f"DuckLakeWriter.write() requires DuckLakeLockToken covering raw table={table.value}"
            )
        self._lock_token.require_data_table(table)

    def _require_provenance_table_lock(self, table: RawDuckLakeProvenanceTable) -> None:
        if self._lock_token is None:
            raise DuckLakeLockViolationError(
                "DuckLakeWriter.upsert_source_object() requires DuckLakeLockToken "
                f"covering provenance table={table.value}"
            )
        self._lock_token.require_provenance_table(table)


############################
# Bootstrap
############################


def bootstrap_raw_ducklake(config: DuckLakeAttachConfig | None = None) -> None:
    attach = config or _build_default_attach_config()
    con = duckdb.connect()
    try:
        _attach(con, config=attach)
        schema_name = f"{_ident(attach.alias)}.{_ident(DEFAULT_RAW_SCHEMA)}"
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
        for table in RawDuckLakeTable:
            quoted_target = _table_sql(attach.alias, _target_for(table))
            table_column_sql = ",\n                    ".join(raw_table_column_definitions(table))
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {quoted_target} (
                    {table_column_sql}
                )
                """
            )
        column_sql = ",\n                ".join(source_object_column_definitions())
        for table in RawDuckLakeProvenanceTable:
            quoted_target = _table_sql(attach.alias, provenance_target_for(table))
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {quoted_target} (
                    {column_sql}
                )
                """
            )
    finally:
        con.close()
