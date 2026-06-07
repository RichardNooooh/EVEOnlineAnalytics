from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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
    raw_table_partition_columns,
    source_object_column_definitions,
)

logger = logging.getLogger("eve_ingest.ducklake")

_IDENTIFIER_RE = re.compile(r"^[^\s-]+$")


def datetime_now_utc() -> datetime:
    return datetime.now(UTC)


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


@dataclass(frozen=True)
class DuckLakeSqlSnapshotSource:
    sql: str


def _attach(
    con: duckdb.DuckDBPyConnection,
    *,
    config: DuckLakeAttachConfig,
) -> None:
    """Load DuckLake extensions and attach target lake into connection."""

    if config.attach_uri.startswith("ducklake:postgres:"):
        con.execute("INSTALL postgres")
        con.execute("LOAD postgres")
        _configure_postgres_pool(con, config=config)
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


def _configure_postgres_pool(con: duckdb.DuckDBPyConnection, *, config: DuckLakeAttachConfig) -> None:
    if config.postgres_pool_max_connections is not None:
        con.execute(f"SET pg_pool_max_connections = {int(config.postgres_pool_max_connections)}")
    if config.postgres_pool_wait_timeout_millis is not None:
        con.execute(f"SET pg_pool_wait_timeout_millis = {int(config.postgres_pool_wait_timeout_millis)}")
    if config.postgres_pool_acquire_mode is not None:
        con.execute(f"SET pg_pool_acquire_mode = {_quote_literal(config.postgres_pool_acquire_mode)}")


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


def _add_missing_columns(
    con: duckdb.DuckDBPyConnection,
    *,
    alias: str,
    target: DuckLakeTableTarget,
    column_definitions: Sequence[str],
) -> None:
    quoted_target = _table_sql(alias, target)
    for column_definition in column_definitions:
        repair_column_definition = column_definition.replace(" NOT NULL", "")
        con.execute(f"ALTER TABLE {quoted_target} ADD COLUMN IF NOT EXISTS {repair_column_definition}")


def _parse_partition_columns(value: object) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        return tuple(part.strip().strip('"') for part in stripped.strip("[]()").split(",") if part.strip())
    return None


def _ducklake_partition_columns(
    con: duckdb.DuckDBPyConnection,
    *,
    target: DuckLakeTableTarget,
) -> tuple[str, ...] | None:
    try:
        row = con.execute(
            """
            SELECT partition_columns
            FROM ducklake_table_info()
            WHERE schema_name = ?
                AND table_name = ?
            """,
            [target.schema, target.table],
        ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return _parse_partition_columns(row[0])


def _ensure_expected_partitioning(
    con: duckdb.DuckDBPyConnection,
    *,
    alias: str,
    target: DuckLakeTableTarget,
    partition_columns: Sequence[str],
) -> None:
    if not partition_columns:
        return

    expected = tuple(partition_columns)
    current = _ducklake_partition_columns(con, target=target)
    if current == expected:
        return
    if current not in {None, ()}:
        raise RuntimeError(
            "DuckLake table partitioning differs from expected layout; rebuild or migrate table "
            f"{target.schema}.{target.table} current={current} expected={expected}"
        )

    quoted_target = _table_sql(alias, target)
    try:
        con.execute(
            f"""
            ALTER TABLE {quoted_target}
            SET PARTITIONED BY ({", ".join(_ident(column) for column in expected)})
            """
        )
    except Exception as exc:
        if "SET PARTITIONED BY is not supported for DuckDB tables" not in str(exc):
            raise
        logger.debug("Skipping DuckLake partition DDL for non-DuckLake table=%s", target.table)


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
                mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
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
        self._transaction_rollback_only = False

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

        `APPEND_SNAPSHOT_ROWS` appends every source row without key validation.
        `ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS` inserts previously unseen
        market-history keys after asserting matched rows are identical and target source-date
        coverage is present in the incoming source. `REPLACE_TABLE` replaces the whole
        target table from the incoming Arrow table.

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
                mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
            )
            ```
        """

        self.validate_write_request(arrow_table, table=table, mode=mode, key_columns=key_columns)
        with self.prepare_arrow_source(arrow_table) as source_name:
            return self.write_prepared_source(
                arrow_table,
                source_name=source_name,
                table=table,
                mode=mode,
                key_columns=key_columns,
            )

    def quote_sql_string(self, value: str) -> str:
        return _quote_literal(value)

    @contextmanager
    def prepare_arrow_source(self, arrow_table: pa.Table) -> Iterator[str]:
        con = self._con
        if con is None:
            raise RuntimeError("Missing DB connection. DuckLakeWriter must be used inside a with block")
        with _arrow_view(con, arrow_table) as source_name:
            yield source_name

    @contextmanager
    def prepare_sql_source(self, sql_source: DuckLakeSqlSnapshotSource) -> Iterator[str]:
        con = self._con
        if con is None:
            raise RuntimeError("Missing DB connection. DuckLakeWriter must be used inside a with block")
        source_name = f"_sql_source_{uuid4().hex}"
        con.execute(f"CREATE OR REPLACE TEMP VIEW {_ident(source_name)} AS {sql_source.sql}")
        try:
            yield source_name
        finally:
            con.execute(f"DROP VIEW IF EXISTS {_ident(source_name)}")

    def validate_write_request(
        self,
        arrow_table: pa.Table,
        *,
        table: RawDuckLakeTable,
        mode: DuckLakeWriterMode,
        key_columns: Sequence[str] = (),
    ) -> None:
        if self._con is None:
            raise RuntimeError("Missing DB connection. DuckLakeWriter must be used inside a with block")
        if self._declared_mode is not None and mode != self._declared_mode:
            requested_mode = getattr(mode, "value", str(mode))
            raise ValueError(
                "DuckLake writer mode does not match publisher declaration "
                f"dataset={self._dataset_name or '-'} table={table.value} "
                f"declared_mode={self._declared_mode.value} requested_mode={requested_mode}"
            )
        self._require_data_table_lock(table)
        if mode is DuckLakeWriterMode.REPLACE_TABLE and len(arrow_table) == 0:
            raise ValueError("REPLACE_TABLE requires a non-empty arrow_table")
        if mode is DuckLakeWriterMode.REPLACE_TABLE and key_columns:
            raise ValueError("REPLACE_TABLE does not accept key_columns")
        if mode is DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS:
            if key_columns:
                raise ValueError("APPEND_SNAPSHOT_ROWS does not accept key_columns")
            required_columns = ["source_object_id", "source_market_date"]
            if table in {RawDuckLakeTable.MARKET_ORDERS, RawDuckLakeTable.FUZZWORK_ORDERS}:
                required_columns.append("snapshot_ts")
            missing_columns = [column for column in required_columns if column not in arrow_table.column_names]
            if missing_columns:
                raise ValueError("APPEND_SNAPSHOT_ROWS requires arrow_table columns: " + ", ".join(missing_columns))
            return
        if mode is DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS:
            _validate_key_columns(arrow_table, key_columns)
            return
        if mode is not DuckLakeWriterMode.REPLACE_TABLE:
            raise ValueError(f"Unsupported DuckLake writer mode: {mode}")

    def write_prepared_source(
        self,
        arrow_table: pa.Table,
        *,
        source_name: str,
        table: RawDuckLakeTable,
        mode: DuckLakeWriterMode,
        key_columns: Sequence[str] = (),
    ) -> DuckLakeWriteMetrics:
        self.validate_write_request(arrow_table, table=table, mode=mode, key_columns=key_columns)

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

        quoted_target = _table_sql(self._attach.alias, _target_for(table))
        quoted_source = _ident(source_name)
        target = _target_for(table)

        if mode is DuckLakeWriterMode.REPLACE_TABLE:
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
            self._record_write_metrics(metrics, key_columns=key_columns)
            return metrics

        if mode is DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS:
            metrics = self._append_snapshot_prepared_source(
                source_name=source_name,
                table=table,
                attempted_rows=len(arrow_table),
            )
            return metrics

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
        self._record_write_metrics(metrics, key_columns=key_columns)
        return metrics

    def _record_write_metrics(self, metrics: DuckLakeWriteMetrics, *, key_columns: Sequence[str]) -> None:
        self._write_history.append(metrics)
        logger.debug(
            "DuckLake write complete table=%s mode=%s attempted_rows=%d inserted_rows=%d matched_rows=%d replaced_rows=%d key_columns=%s",
            metrics.table.value,
            metrics.mode.value,
            metrics.attempted_rows,
            metrics.inserted_rows,
            metrics.matched_rows,
            metrics.replaced_rows,
            list(key_columns),
        )

    def publish_source_object_rows(
        self,
        arrow_table: pa.Table,
        *,
        data_table: RawDuckLakeTable,
        provenance_table: RawDuckLakeProvenanceTable,
        source_object_id: str,
        mode: DuckLakeWriterMode,
        row_count: int,
        key_columns: Sequence[str] = (),
    ) -> DuckLakeWriteMetrics:
        """Mark parsed, write rows, and mark ingested in one transaction."""

        self.validate_write_request(arrow_table, table=data_table, mode=mode, key_columns=key_columns)
        with self.prepare_arrow_source(arrow_table) as source_name:
            with self.transaction():
                self.mark_source_object_parsed(source_object_id, table=provenance_table)
                metrics = self.write_prepared_source(
                    arrow_table,
                    source_name=source_name,
                    table=data_table,
                    mode=mode,
                    key_columns=key_columns,
                )
                self.mark_source_object_ingested(source_object_id, row_count=row_count, table=provenance_table)
                return metrics

    def publish_source_object_sql_rows(
        self,
        sql_source: DuckLakeSqlSnapshotSource,
        *,
        data_table: RawDuckLakeTable,
        provenance_table: RawDuckLakeProvenanceTable,
        source_object_id: str,
        mode: DuckLakeWriterMode,
    ) -> DuckLakeWriteMetrics:
        if mode is not DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS:
            raise ValueError("publish_source_object_sql_rows only supports APPEND_SNAPSHOT_ROWS")
        self._require_data_table_lock(data_table)
        with self.prepare_sql_source(sql_source) as source_name:
            quoted_source = _ident(source_name)
            row_count = int(self._con.execute(f"SELECT COUNT(*) FROM {quoted_source}").fetchone()[0])
            with self.transaction():
                self.mark_source_object_parsed(source_object_id, table=provenance_table)
                metrics = self._append_snapshot_prepared_source(
                    source_name=source_name,
                    table=data_table,
                    attempted_rows=row_count,
                )
                self.mark_source_object_ingested(source_object_id, row_count=row_count, table=provenance_table)
                return metrics

    def _append_snapshot_prepared_source(
        self,
        *,
        source_name: str,
        table: RawDuckLakeTable,
        attempted_rows: int,
    ) -> DuckLakeWriteMetrics:
        con = self._con
        if con is None:
            raise RuntimeError("Missing DB connection. DuckLakeWriter must be used inside a with block")

        target = _target_for(table)
        _require_table(con, alias=self._attach.alias, target=target)
        quoted_target = _table_sql(self._attach.alias, target)
        quoted_source = _ident(source_name)
        con.execute(
            f"""
            INSERT INTO {quoted_target} BY NAME
            SELECT * FROM {quoted_source}
            """
        )
        metrics = DuckLakeWriteMetrics(
            table=table,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
            attempted_rows=attempted_rows,
            inserted_rows=attempted_rows,
            matched_rows=0,
            replaced_rows=0,
        )
        self._record_write_metrics(metrics, key_columns=())
        return metrics

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
            self._transaction_rollback_only = True
            self._transaction_depth -= 1
            if outermost:
                self._transaction_depth = 0
                self._transaction_rollback_only = False
                con.execute("ROLLBACK")
            raise
        else:
            self._transaction_depth -= 1
            if outermost:
                if self._transaction_rollback_only:
                    self._transaction_rollback_only = False
                    con.execute("ROLLBACK")
                    raise RuntimeError("DuckLake transaction marked rollback-only by nested failure")
                try:
                    con.execute("COMMIT")
                except Exception:
                    try:
                        con.execute("ROLLBACK")
                    except Exception:
                        logger.exception("Failed to rollback after DuckLake commit failure")
                    raise

    def record_source_object(self, metadata: dict, *, table: RawDuckLakeProvenanceTable) -> None:
        self._merge_source_object(metadata, table=table)

    def mark_source_object_parsed(self, source_object_id: str, *, table: RawDuckLakeProvenanceTable) -> None:
        self._update_source_object_status(
            source_object_id,
            table=table,
            data={"status": "parsed", "parsed_at": datetime_now_utc(), "status_reason": None},
        )

    def mark_source_object_ingested(
        self,
        source_object_id: str,
        *,
        row_count: int,
        table: RawDuckLakeProvenanceTable,
    ) -> None:
        self._update_source_object_status(
            source_object_id,
            table=table,
            data={
                "status": "ingested",
                "ingested_at": datetime_now_utc(),
                "row_count": row_count,
                "status_reason": None,
            },
        )

    def mark_source_object_failed(
        self,
        source_object_id: str,
        *,
        reason: str,
        table: RawDuckLakeProvenanceTable,
    ) -> None:
        self._update_source_object_status(
            source_object_id,
            table=table,
            data={"status": "failed", "status_reason": reason},
        )

    def _merge_source_object(self, data: dict, *, table: RawDuckLakeProvenanceTable) -> None:
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

    def _update_source_object_status(
        self,
        source_object_id: str,
        *,
        table: RawDuckLakeProvenanceTable,
        data: dict,
    ) -> None:
        con = self._con
        if con is None:
            raise RuntimeError("Missing DB connection. DuckLakeWriter must be used inside a with block")
        self._require_provenance_table_lock(table)

        quoted_target = _table_sql(self._attach.alias, provenance_target_for(table))
        columns = list(data.keys())
        set_list = ", ".join(f"{_ident(column)} = ?" for column in columns)
        rows = con.execute(
            f"""
            UPDATE {quoted_target}
            SET {set_list}
            WHERE source_object_id = ?
            RETURNING source_object_id
            """,
            [*data.values(), source_object_id],
        ).fetchall()
        if not rows:
            raise RuntimeError(f"Missing source object provenance row source_object_id={source_object_id}")

    def source_object_version_is_ingested(
        self,
        source_object_id: str,
        *,
        sha256: str,
        table: RawDuckLakeProvenanceTable,
    ) -> bool:
        con = self._con
        if con is None:
            raise RuntimeError("Missing DB connection. DuckLakeWriter must be used inside a with block")
        self._require_provenance_table_lock(table)

        quoted_target = _table_sql(self._attach.alias, provenance_target_for(table))
        row = con.execute(
            f"""
            SELECT 1
            FROM {quoted_target}
            WHERE source_object_id = ?
                AND status = 'ingested'
                AND sha256 = ?
            LIMIT 1
            """,
            [source_object_id, sha256],
        ).fetchone()
        return row is not None

    def source_object_ingested_sha256(
        self,
        source_object_id: str,
        *,
        table: RawDuckLakeProvenanceTable,
    ) -> str | None:
        con = self._con
        if con is None:
            raise RuntimeError("Missing DB connection. DuckLakeWriter must be used inside a with block")
        self._require_provenance_table_lock(table)

        quoted_target = _table_sql(self._attach.alias, provenance_target_for(table))
        row = con.execute(
            f"""
            SELECT sha256
            FROM {quoted_target}
            WHERE source_object_id = ?
                AND status = 'ingested'
            LIMIT 1
            """,
            [source_object_id],
        ).fetchone()
        if row is None:
            return None
        return row[0]

    def _require_data_table_lock(self, table: RawDuckLakeTable) -> None:
        if self._lock_token is None:
            raise DuckLakeLockViolationError(
                f"DuckLakeWriter.write() requires DuckLakeLockToken covering raw table={table.value}"
            )
        self._lock_token.require_data_table(table)

    def _require_provenance_table_lock(self, table: RawDuckLakeProvenanceTable) -> None:
        if self._lock_token is None:
            raise DuckLakeLockViolationError(
                f"DuckLakeWriter provenance methods require DuckLakeLockToken covering provenance table={table.value}"
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
            target = _target_for(table)
            quoted_target = _table_sql(attach.alias, target)
            table_column_sql = ",\n                    ".join(raw_table_column_definitions(table))
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {quoted_target} (
                    {table_column_sql}
                )
                """
            )
            _add_missing_columns(
                con,
                alias=attach.alias,
                target=target,
                column_definitions=raw_table_column_definitions(table),
            )
            partition_columns = raw_table_partition_columns(table)
            if partition_columns:
                _ensure_expected_partitioning(
                    con,
                    alias=attach.alias,
                    target=target,
                    partition_columns=partition_columns,
                )
        column_sql = ",\n                ".join(source_object_column_definitions())
        for table in RawDuckLakeProvenanceTable:
            target = provenance_target_for(table)
            quoted_target = _table_sql(attach.alias, target)
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {quoted_target} (
                    {column_sql}
                )
                """
            )
            _add_missing_columns(
                con,
                alias=attach.alias,
                target=target,
                column_definitions=source_object_column_definitions(),
            )
    finally:
        con.close()
