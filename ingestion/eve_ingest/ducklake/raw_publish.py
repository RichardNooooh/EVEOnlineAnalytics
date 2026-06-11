from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from eve_ingest.ducklake.locks import DuckLakeLockToken, DuckLakeLockViolationError
from eve_ingest.ducklake.raw_tables import (
    DuckLakeTableTarget,
    DuckLakeWriteMetrics,
    DuckLakeWriterMode,
    RawDuckLakeTable,
    _target_for,
)
from eve_ingest.ducklake.sql import (
    count_source_rows_with_matches,
    count_source_rows_without_matches,
    quote_identifier,
    table_sql,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import duckdb
    import pyarrow as pa

    from eve_ingest.ducklake.session import DuckLakeSession

logger = logging.getLogger(__name__)


def validate_key_columns(arrow_table: pa.Table, key_columns: Sequence[str]) -> None:
    if not key_columns:
        raise ValueError("key_columns must not be empty when writer mode requires keys")
    for key in key_columns:
        quote_identifier(key)
    missing_key_columns = [key for key in key_columns if key not in arrow_table.column_names]
    if missing_key_columns:
        raise ValueError("key_columns must exist in arrow_table columns: " + ", ".join(missing_key_columns))


def target_exists(con: duckdb.DuckDBPyConnection, *, alias: str, target: DuckLakeTableTarget) -> bool:
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


def require_table(con: duckdb.DuckDBPyConnection, *, alias: str, target: DuckLakeTableTarget) -> None:
    if target_exists(con, alias=alias, target=target):
        return
    raise RuntimeError(
        f"Missing bootstrapped raw table {target.schema}.{target.table}. "
        "Run `eve-ingest ducklake bootstrap raw` before publication."
    )


def add_missing_columns(
    con: duckdb.DuckDBPyConnection,
    *,
    alias: str,
    target: DuckLakeTableTarget,
    column_definitions: Sequence[str],
) -> None:
    quoted_target = table_sql(alias, target)
    for column_definition in column_definitions:
        repair_column_definition = column_definition.replace(" NOT NULL", "")
        con.execute(f"ALTER TABLE {quoted_target} ADD COLUMN IF NOT EXISTS {repair_column_definition}")


def parse_partition_columns(value: object) -> tuple[str, ...] | None:
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


def ducklake_partition_columns(
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
    return parse_partition_columns(row[0])


def ensure_expected_partitioning(
    con: duckdb.DuckDBPyConnection,
    *,
    alias: str,
    target: DuckLakeTableTarget,
    partition_columns: Sequence[str],
) -> None:
    if not partition_columns:
        return
    expected = tuple(partition_columns)
    current = ducklake_partition_columns(con, target=target)
    if current == expected:
        return
    if current not in {None, ()}:
        raise RuntimeError(
            "DuckLake table partitioning differs from expected layout; rebuild or migrate table "
            f"{target.schema}.{target.table} current={current} expected={expected}"
        )
    quoted_target = table_sql(alias, target)
    try:
        con.execute(
            f"""
            ALTER TABLE {quoted_target}
            SET PARTITIONED BY ({", ".join(quote_identifier(column) for column in expected)})
            """
        )
    except Exception as exc:
        if "SET PARTITIONED BY is not supported for DuckDB tables" not in str(exc):
            raise
        logger.debug("Skipping DuckLake partition DDL for non-DuckLake table=%s", target.table)


def assert_matched_key_rows_identical(
    con: duckdb.DuckDBPyConnection,
    arrow_table: pa.Table,
    *,
    quoted_target: str,
    quoted_source: str,
    key_columns: Sequence[str],
) -> None:
    non_key_cols = [col for col in arrow_table.column_names if col not in key_columns and not col.startswith("_")]
    if not non_key_cols:
        return
    key_join = " AND ".join(f"s.{quote_identifier(k)} = t.{quote_identifier(k)}" for k in key_columns)
    key_list = ", ".join(f"s.{quote_identifier(k)}" for k in key_columns)
    where_clause = " OR ".join(
        f"s.{quote_identifier(c)} IS DISTINCT FROM t.{quote_identifier(c)}" for c in non_key_cols
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
        raise ValueError("Could not query target for key validation") from None
    if differing:
        examples = ", ".join(
            ", ".join(f"{key}={value!r}" for key, value in zip(key_columns, row, strict=False))
            for row in differing[:10]
        )
        raise ValueError(f"Matched key rows have differing values: {examples}")


def assert_target_rows_missing_from_source(
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
    key_join = " AND ".join(f"s.{quote_identifier(k)} = t.{quote_identifier(k)}" for k in key_columns)
    key_list = ", ".join(f"t.{quote_identifier(k)}" for k in key_columns)
    query = f"""
        WITH source_dates AS (
            SELECT DISTINCT {quoted_source}.{quote_identifier(source_date_col)} AS source_date
            FROM {quoted_source}
        )
        SELECT t.{quote_identifier(source_date_col)} AS source_date, {key_list}
        FROM {quoted_target} t
        JOIN source_dates sd
            ON t.{quote_identifier(source_date_col)} = sd.source_date
        WHERE NOT EXISTS (
            SELECT 1
            FROM {quoted_source} s
            WHERE s.{quote_identifier(source_date_col)} = t.{quote_identifier(source_date_col)}
                AND {key_join}
        )
    """
    try:
        missing = con.execute(query).fetchall()
    except Exception as exc:
        raise ValueError("Could not query target for source-date coverage check") from exc
    if missing:
        examples = ", ".join(
            f"source_date={row[0]!r}, keys={dict(zip(key_columns, row[1:], strict=False))!r}" for row in missing[:10]
        )
        raise ValueError(f"Target has rows for source_date(s) absent from the newly downloaded source file: {examples}")


class RawTablePublisher:
    def __init__(
        self,
        session: DuckLakeSession,
        *,
        lock_token: DuckLakeLockToken | None = None,
        declared_policy: DuckLakeWriterMode | None = None,
        dataset_name: str | None = None,
    ) -> None:
        self._session = session
        self._lock_token = lock_token
        self._declared_policy = declared_policy
        self._dataset_name = dataset_name
        self._write_history: list[DuckLakeWriteMetrics] = []

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
        self.validate_write_request(arrow_table, table=table, mode=mode, key_columns=key_columns)
        with self._session.prepare_arrow_source(arrow_table) as source_name:
            return self.write_prepared_source(
                arrow_table,
                source_name=source_name,
                table=table,
                mode=mode,
                key_columns=key_columns,
            )

    def validate_write_request(
        self,
        arrow_table: pa.Table,
        *,
        table: RawDuckLakeTable,
        mode: DuckLakeWriterMode,
        key_columns: Sequence[str] = (),
    ) -> None:
        self._require_data_table_lock(table)
        if self._declared_policy is not None and mode != self._declared_policy:
            requested_mode = getattr(mode, "value", str(mode))
            raise ValueError(
                "DuckLake writer mode does not match publisher declaration "
                f"dataset={self._dataset_name or '-'} table={table.value} "
                f"declared_mode={self._declared_policy.value} requested_mode={requested_mode}"
            )
        if mode is DuckLakeWriterMode.REPLACE_TABLE and len(arrow_table) == 0:
            raise ValueError("REPLACE_TABLE requires a non-empty arrow_table")
        if mode is DuckLakeWriterMode.REPLACE_TABLE and key_columns:
            raise ValueError("REPLACE_TABLE does not accept key_columns")
        if mode is DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS:
            if key_columns:
                raise ValueError("APPEND_SNAPSHOT_ROWS does not accept key_columns")
            required_columns = ["source_ref_id", "source_market_date"]
            if table in {RawDuckLakeTable.MARKET_ORDERS, RawDuckLakeTable.FUZZWORK_ORDERS}:
                required_columns.append("snapshot_ts")
            missing_columns = [column for column in required_columns if column not in arrow_table.column_names]
            if missing_columns:
                raise ValueError("APPEND_SNAPSHOT_ROWS requires arrow_table columns: " + ", ".join(missing_columns))
            return
        if mode is DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS:
            validate_key_columns(arrow_table, key_columns)
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

        con = self._session.connection
        alias = self._session.alias

        logger.debug(
            "Writing to DuckLake table=%s rows=%d columns=%d key_columns=%s mode=%s",
            table.value,
            len(arrow_table),
            len(arrow_table.column_names),
            list(key_columns),
            mode.value,
        )

        quoted_target = table_sql(alias, _target_for(table))
        quoted_source = quote_identifier(source_name)
        target = _target_for(table)

        if mode is DuckLakeWriterMode.REPLACE_TABLE:
            require_table(con, alias=alias, target=target)
            row = con.execute(f"SELECT COUNT(*) FROM {quoted_target}").fetchone()
            assert row is not None
            replaced_rows = int(row[0])
            with self._session.transaction():
                con.execute(f"DELETE FROM {quoted_target}")
                con.execute(
                    f"""
                    INSERT INTO {quoted_target} BY NAME
                    SELECT * FROM {quoted_source}
                    """
                )
            row = con.execute(f"SELECT COUNT(*) FROM {quoted_source}").fetchone()
            assert row is not None
            attempted_rows = int(row[0])
            metrics = DuckLakeWriteMetrics(
                table=table,
                mode=mode,
                attempted_rows=attempted_rows,
                inserted_rows=attempted_rows,
                matched_rows=0,
                replaced_rows=replaced_rows,
            )
            self._record_write_metrics(metrics, key_columns=key_columns)
            return metrics

        if mode is DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS:
            metrics = self._append_snapshot_prepared_source(
                source_name=source_name,
                table=table,
            )
            return metrics

        require_table(con, alias=alias, target=target)
        assert_matched_key_rows_identical(
            con,
            arrow_table,
            quoted_target=quoted_target,
            quoted_source=quoted_source,
            key_columns=key_columns,
        )
        if mode is DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS:
            assert_target_rows_missing_from_source(
                con,
                arrow_table,
                quoted_target=quoted_target,
                quoted_source=quoted_source,
                key_columns=key_columns,
            )

        matched_rows = count_source_rows_with_matches(
            con,
            quoted_target=quoted_target,
            quoted_source=quoted_source,
            key_columns=list(key_columns),
        )
        inserted_rows = count_source_rows_without_matches(
            con,
            quoted_target=quoted_target,
            quoted_source=quoted_source,
            key_columns=list(key_columns),
        )

        con.execute(
            f"""
            MERGE INTO {quoted_target} AS target
            USING {quoted_source} AS source
            USING ({", ".join(quote_identifier(key) for key in key_columns)})
            WHEN NOT MATCHED THEN INSERT BY NAME
            """
        )
        metrics = DuckLakeWriteMetrics(
            table=table,
            mode=mode,
            attempted_rows=matched_rows + inserted_rows,
            inserted_rows=inserted_rows,
            matched_rows=matched_rows,
            replaced_rows=0,
        )
        self._record_write_metrics(metrics, key_columns=key_columns)
        return metrics

    def append_snapshot_prepared_source(
        self,
        *,
        source_name: str,
        table: RawDuckLakeTable,
    ) -> DuckLakeWriteMetrics:
        return self._append_snapshot_prepared_source(
            source_name=source_name,
            table=table,
        )

    def _append_snapshot_prepared_source(
        self,
        *,
        source_name: str,
        table: RawDuckLakeTable,
    ) -> DuckLakeWriteMetrics:
        con = self._session.connection
        alias = self._session.alias

        target = _target_for(table)
        require_table(con, alias=alias, target=target)
        quoted_target = table_sql(alias, target)
        quoted_source = quote_identifier(source_name)
        con.execute(
            f"""
            INSERT INTO {quoted_target} BY NAME
            SELECT * FROM {quoted_source}
            """
        )
        row = con.execute(f"SELECT COUNT(*) FROM {quoted_source}").fetchone()
        assert row is not None
        attempted_rows = int(row[0])
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

    def _require_data_table_lock(self, table: RawDuckLakeTable) -> None:
        if self._lock_token is None:
            raise DuckLakeLockViolationError(
                f"RawTablePublisher.write() requires DuckLakeLockToken covering raw table={table.value}"
            )
        self._lock_token.require_data_table(table)
