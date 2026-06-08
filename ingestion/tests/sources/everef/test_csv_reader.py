from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, date, datetime

import pyarrow as pa
import pytest

from eve_ingest.ducklake.writer import DuckLakeSqlSnapshotSource
from eve_ingest.ducklake.raw_tables import DuckLakeWriteMetrics, DuckLakeWriterMode, RawDuckLakeTable
from eve_ingest.sources.everef import csv_reader
from eve_ingest.sources.everef.csv_reader import publish_file_backed_rows, publish_file_backed_snapshot_rows
from eve_ingest.workflows.publication_errors import SnapshotScopePublishError
from eve_ingest.sources.everef.provenance import parse_last_modified_timestamp
from tests.sources.everef.conftest import make_cache_result


class _FakeWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.transaction_exit_exceptions: list[Exception | None] = []
        self.ingested_sha256: str | None = None

    def source_object_ingested_sha256(self, source_object_id: str, *, table) -> str | None:
        self.calls.append(("source_object_ingested_sha256", {"source_object_id": source_object_id, "table": table}))
        return self.ingested_sha256

    def source_object_version_is_ingested(self, source_object_id: str, *, sha256: str, table) -> bool:
        self.calls.append(
            (
                "source_object_version_is_ingested",
                {"source_object_id": source_object_id, "sha256": sha256, "table": table},
            )
        )
        return self.ingested_sha256 == sha256

    @contextmanager
    def transaction(self):
        self.calls.append(("transaction_enter", None))
        try:
            yield
        except Exception:
            self.calls.append(("transaction_rollback", None))
            raise
        else:
            if self.transaction_exit_exceptions:
                exc = self.transaction_exit_exceptions.pop(0)
                if exc is not None:
                    self.calls.append(("transaction_commit_error", str(exc)))
                    raise exc
            self.calls.append(("transaction_commit", None))

    def record_source_object(self, metadata: dict, *, table) -> None:
        self.calls.append(("record", metadata.copy()))

    def mark_source_object_parsed(self, source_object_id: str, *, table) -> None:
        self.calls.append(("mark_parsed", {"source_object_id": source_object_id, "table": table}))

    def mark_source_object_ingested(self, source_object_id: str, *, row_count: int, table) -> None:
        self.calls.append(
            ("mark_ingested", {"source_object_id": source_object_id, "row_count": row_count, "table": table})
        )

    def mark_source_object_failed(self, source_object_id: str, *, reason: str, table) -> None:
        self.calls.append(("mark_failed", {"source_object_id": source_object_id, "reason": reason, "table": table}))

    def publish_source_object_rows(
        self,
        arrow_table: pa.Table,
        *,
        data_table: RawDuckLakeTable,
        provenance_table,
        source_object_id: str,
        mode: DuckLakeWriterMode,
        row_count: int,
        key_columns: list[str],
    ):
        with self.transaction():
            self.mark_source_object_parsed(source_object_id, table=provenance_table)
            self.calls.append(
                (
                    "publish_rows",
                    {
                        "table": data_table,
                        "mode": mode,
                        "key_columns": key_columns,
                        "rows": len(arrow_table),
                        "columns": tuple(arrow_table.column_names),
                    },
                )
            )
            self.mark_source_object_ingested(source_object_id, row_count=row_count, table=provenance_table)
        return DuckLakeWriteMetrics(
            table=data_table,
            mode=mode,
            attempted_rows=len(arrow_table),
            inserted_rows=len(arrow_table),
            matched_rows=0,
            replaced_rows=0,
        )

    def publish_source_object_sql_rows(
        self,
        sql_source: DuckLakeSqlSnapshotSource,
        *,
        data_table: RawDuckLakeTable,
        provenance_table,
        source_object_id: str,
        mode: DuckLakeWriterMode,
        row_count: int | None = None,
    ):
        with self.transaction():
            self.mark_source_object_parsed(source_object_id, table=provenance_table)
            self.calls.append(
                (
                    "publish_sql_rows",
                    {
                        "table": data_table,
                        "mode": mode,
                        "sql": sql_source.sql.strip(),
                    },
                )
            )
            self.mark_source_object_ingested(source_object_id, row_count=0, table=provenance_table)
        return DuckLakeWriteMetrics(
            table=data_table,
            mode=mode,
            attempted_rows=0,
            inserted_rows=0,
            matched_rows=0,
            replaced_rows=0,
        )

    def write(
        self,
        arrow_table: pa.Table,
        *,
        table: RawDuckLakeTable,
        mode: DuckLakeWriterMode,
        key_columns: list[str],
    ):
        self.calls.append(
            (
                "write",
                {
                    "table": table,
                    "mode": mode,
                    "key_columns": key_columns,
                    "rows": len(arrow_table),
                    "columns": tuple(arrow_table.column_names),
                },
            )
        )
        return DuckLakeWriteMetrics(
            table=table,
            mode=mode,
            attempted_rows=len(arrow_table),
            inserted_rows=len(arrow_table),
            matched_rows=0,
            replaced_rows=0,
        )


def test_publish_file_backed_rows_groups_write_and_success_provenance_after_initial_record() -> None:
    result = make_cache_result(
        "/tmp/market-history-2026-01-01.csv.bz2",
        source_url="https://example.com/market-history-2026-01-01.csv.bz2",
    )
    writer = _FakeWriter()
    parsed_table = pa.table({"type_id": [34], "average": [5.25]})

    outcome = publish_file_backed_rows(
        result,
        writer,
        source_system="everef",
        endpoint="market_history",
        source_market_date=date(2026, 1, 1),
        table_key=RawDuckLakeTable.MARKET_HISTORY,
        mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
        key_columns=["type_id"],
        parse_table=lambda _: parsed_table,
    )

    assert outcome.success is True
    assert [call[0] for call in writer.calls] == [
        "record",
        "transaction_enter",
        "mark_parsed",
        "publish_rows",
        "mark_ingested",
        "transaction_commit",
    ]
    assert writer.calls[1][0] == "transaction_enter"
    assert writer.calls[2][0] == "mark_parsed"
    assert writer.calls[3][1]["columns"] == ("type_id", "average", "source_object_id", "source_market_date")
    assert writer.calls[4][0] == "mark_ingested"
    assert writer.calls[0][1]["source_object_id"] == writer.calls[2][1]["source_object_id"]
    assert writer.calls[0][1]["source_object_id"] == writer.calls[4][1]["source_object_id"]


def test_publish_file_backed_rows_skips_already_ingested_source_object() -> None:
    result = make_cache_result(
        "/tmp/market-orders-2026-01-01.csv.bz2",
        dataset_name="market-orders",
        source_url="https://example.com/market-orders-2026-01-01.csv.bz2",
    )
    writer = _FakeWriter()
    writer.ingested_sha256 = result.version.sha256

    def parse_table(_):
        raise AssertionError("already-ingested source should not be parsed")

    outcome = publish_file_backed_rows(
        result,
        writer,
        source_system="everef",
        endpoint="market_orders",
        source_market_date=date(2026, 1, 1),
        table_key=RawDuckLakeTable.MARKET_ORDERS,
        mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        key_columns=[],
        parse_table=parse_table,
        snapshot_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert outcome.success is True
    assert outcome.source_date == "2026-01-01"
    assert outcome.write_metrics == ()
    assert [call[0] for call in writer.calls] == ["source_object_ingested_sha256"]


def test_publish_file_backed_rows_raises_when_append_snapshot_source_object_sha_changes() -> None:
    result = make_cache_result(
        "/tmp/market-orders-2026-01-01.csv.bz2",
        dataset_name="market-orders",
        source_url="https://example.com/market-orders-2026-01-01.csv.bz2",
    )
    writer = _FakeWriter()
    writer.ingested_sha256 = "different-sha256"

    def parse_table(_):
        raise AssertionError("changed immutable snapshot source should not be parsed")

    with pytest.raises(
        csv_reader.ImmutableSnapshotSourceObjectChangedError,
        match="snapshot URLs are expected immutable",
    ):
        publish_file_backed_rows(
            result,
            writer,
            source_system="everef",
            endpoint="market_orders",
            source_market_date=date(2026, 1, 1),
            table_key=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
            key_columns=[],
            parse_table=parse_table,
            snapshot_ts=datetime(2026, 1, 1, tzinfo=UTC),
        )

    assert [call[0] for call in writer.calls] == ["source_object_ingested_sha256"]


def test_publish_file_backed_rows_allows_mutable_non_append_source_object_sha_changes() -> None:
    result = make_cache_result(
        "/tmp/market-history-2026-01-01.csv.bz2",
        source_url="https://example.com/market-history-2026-01-01.csv.bz2",
    )
    writer = _FakeWriter()
    writer.ingested_sha256 = "different-sha256"
    parsed_table = pa.table({"type_id": [34], "average": [5.25]})

    outcome = publish_file_backed_rows(
        result,
        writer,
        source_system="everef",
        endpoint="market_history",
        source_market_date=date(2026, 1, 1),
        table_key=RawDuckLakeTable.MARKET_HISTORY,
        mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
        key_columns=["type_id"],
        parse_table=lambda _: parsed_table,
    )

    assert outcome.success is True
    assert [call[0] for call in writer.calls] == [
        "record",
        "transaction_enter",
        "mark_parsed",
        "publish_rows",
        "mark_ingested",
        "transaction_commit",
    ]


def test_publish_file_backed_rows_marks_failure_after_transaction_rollback() -> None:
    result = make_cache_result(
        "/tmp/market-orders-2026-01-01.csv.bz2",
        dataset_name="market-orders",
        source_url="https://example.com/market-orders-2026-01-01.csv.bz2",
    )
    writer = _FakeWriter()
    parsed_table = pa.table({"order_id": [1], "price": [10.0]})

    def fail_publish(
        arrow_table: pa.Table,
        *,
        data_table: RawDuckLakeTable,
        provenance_table,
        source_object_id: str,
        mode: DuckLakeWriterMode,
        row_count: int,
        key_columns: list[str],
    ):
        writer.calls.append(("publish_rows", {"rows": len(arrow_table)}))
        raise RuntimeError("boom")

    writer.publish_source_object_rows = fail_publish  # type: ignore[method-assign]

    outcome = publish_file_backed_rows(
        result,
        writer,
        source_system="everef",
        endpoint="market_orders",
        source_market_date=date(2026, 1, 1),
        table_key=RawDuckLakeTable.MARKET_ORDERS,
        mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        key_columns=[],
        parse_table=lambda _: parsed_table,
        snapshot_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert outcome.success is False
    assert [call[0] for call in writer.calls] == [
        "source_object_ingested_sha256",
        "record",
        "source_object_ingested_sha256",
        "publish_rows",
        "mark_failed",
    ]
    assert writer.calls[-1][1]["reason"] == "see log for details"


def test_publish_file_backed_rows_retries_retryable_ducklake_conflict(caplog, monkeypatch) -> None:
    result = make_cache_result(
        "/tmp/market-orders-2026-01-01.csv.bz2",
        dataset_name="market-orders",
        source_url="https://example.com/market-orders-2026-01-01.csv.bz2",
    )
    writer = _FakeWriter()
    writer.transaction_exit_exceptions = [RuntimeError("ducklake_snapshot primary key constraint violation"), None]
    parsed_table = pa.table({"order_id": [1], "price": [10.0]})
    sleep_calls: list[float] = []

    monkeypatch.setattr(csv_reader.random, "uniform", lambda start, end: 0.05)
    monkeypatch.setattr(csv_reader.time, "sleep", sleep_calls.append)
    caplog.set_level("WARNING")

    outcome = publish_file_backed_rows(
        result,
        writer,
        source_system="everef",
        endpoint="market_orders",
        source_market_date=date(2026, 1, 1),
        table_key=RawDuckLakeTable.MARKET_ORDERS,
        mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        key_columns=[],
        parse_table=lambda _: parsed_table,
        snapshot_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert outcome.success is True
    assert [call[0] for call in writer.calls] == [
        "source_object_ingested_sha256",
        "record",
        "source_object_ingested_sha256",
        "transaction_enter",
        "mark_parsed",
        "publish_rows",
        "mark_ingested",
        "transaction_commit_error",
        "source_object_ingested_sha256",
        "transaction_enter",
        "mark_parsed",
        "publish_rows",
        "mark_ingested",
        "transaction_commit",
    ]
    assert sleep_calls == [pytest.approx(0.25)]
    assert "Retrying DuckLake insert-style publication after conflict" in caplog.text


def test_publish_file_backed_rows_retries_retryable_ducklake_conflict_after_rollback(caplog, monkeypatch) -> None:
    result = make_cache_result(
        "/tmp/market-orders-2026-01-01.csv.bz2",
        dataset_name="market-orders",
        source_url="https://example.com/market-orders-2026-01-01.csv.bz2",
    )
    writer = _FakeWriter()
    parsed_table = pa.table({"order_id": [1], "price": [10.0]})
    sleep_calls: list[float] = []
    write_attempts = 0

    def fail_once_publish(
        arrow_table: pa.Table,
        *,
        data_table: RawDuckLakeTable,
        provenance_table,
        source_object_id: str,
        mode: DuckLakeWriterMode,
        row_count: int,
        key_columns: list[str],
    ):
        nonlocal write_attempts
        write_attempts += 1
        writer.calls.append(
            (
                "write_prepared",
                {
                    "table": data_table,
                    "mode": mode,
                    "key_columns": key_columns,
                    "rows": len(arrow_table),
                    "columns": tuple(arrow_table.column_names),
                    "attempt": write_attempts,
                },
            )
        )
        if write_attempts == 1:
            raise RuntimeError("ducklake_snapshot primary key constraint violation")
        return DuckLakeWriteMetrics(
            table=data_table,
            mode=mode,
            attempted_rows=len(arrow_table),
            inserted_rows=len(arrow_table),
            matched_rows=0,
            replaced_rows=0,
        )

    writer.publish_source_object_rows = fail_once_publish  # type: ignore[method-assign]
    monkeypatch.setattr(csv_reader.random, "uniform", lambda start, end: 0.05)
    monkeypatch.setattr(csv_reader.time, "sleep", sleep_calls.append)
    caplog.set_level("WARNING")

    outcome = publish_file_backed_rows(
        result,
        writer,
        source_system="everef",
        endpoint="market_orders",
        source_market_date=date(2026, 1, 1),
        table_key=RawDuckLakeTable.MARKET_ORDERS,
        mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        key_columns=[],
        parse_table=lambda _: parsed_table,
        snapshot_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert outcome.success is True
    assert [call[0] for call in writer.calls] == [
        "source_object_ingested_sha256",
        "record",
        "source_object_ingested_sha256",
        "write_prepared",
        "source_object_ingested_sha256",
        "write_prepared",
    ]
    assert writer.calls[3][1]["attempt"] == 1
    assert writer.calls[5][1]["attempt"] == 2
    assert sleep_calls == [pytest.approx(0.25)]
    assert "Retrying DuckLake insert-style publication after conflict" in caplog.text


def test_publish_file_backed_rows_does_not_retry_non_conflict_failure(monkeypatch) -> None:
    result = make_cache_result(
        "/tmp/market-orders-2026-01-01.csv.bz2",
        dataset_name="market-orders",
        source_url="https://example.com/market-orders-2026-01-01.csv.bz2",
    )
    writer = _FakeWriter()
    writer.transaction_exit_exceptions = [RuntimeError("boom")]
    parsed_table = pa.table({"order_id": [1], "price": [10.0]})
    sleep_calls: list[float] = []

    monkeypatch.setattr(csv_reader.time, "sleep", sleep_calls.append)

    outcome = publish_file_backed_rows(
        result,
        writer,
        source_system="everef",
        endpoint="market_orders",
        source_market_date=date(2026, 1, 1),
        table_key=RawDuckLakeTable.MARKET_ORDERS,
        mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        key_columns=[],
        parse_table=lambda _: parsed_table,
        snapshot_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert outcome.success is False
    assert [call[0] for call in writer.calls] == [
        "source_object_ingested_sha256",
        "record",
        "source_object_ingested_sha256",
        "transaction_enter",
        "mark_parsed",
        "publish_rows",
        "mark_ingested",
        "transaction_commit_error",
        "mark_failed",
    ]
    assert sleep_calls == []


def test_publish_file_backed_snapshot_rows_groups_write_and_success_provenance_after_initial_record() -> None:
    result = make_cache_result(
        "/tmp/market-orders-2026-01-01.csv.bz2",
        dataset_name="market-orders",
        source_url="https://example.com/market-orders-2026-01-01.csv.bz2",
    )
    writer = _FakeWriter()

    outcome = publish_file_backed_snapshot_rows(
        result,
        writer,
        source_system="everef",
        endpoint="market_orders",
        source_market_date=date(2026, 1, 1),
        snapshot_ts=datetime(2026, 1, 1, tzinfo=UTC),
        table_key=RawDuckLakeTable.MARKET_ORDERS,
        sql_source=DuckLakeSqlSnapshotSource(sql="select 1"),
    )

    assert outcome.success is True
    assert [call[0] for call in writer.calls] == [
        "source_object_ingested_sha256",
        "record",
        "source_object_ingested_sha256",
        "transaction_enter",
        "mark_parsed",
        "publish_sql_rows",
        "mark_ingested",
        "transaction_commit",
    ]
    assert writer.calls[1][1]["source_object_id"] == writer.calls[4][1]["source_object_id"]
    assert writer.calls[1][1]["source_object_id"] == writer.calls[6][1]["source_object_id"]


def test_publish_file_backed_snapshot_rows_raises_snapshot_scope_publish_error() -> None:
    result = make_cache_result(
        "/tmp/market-orders-2026-01-01.csv.bz2",
        dataset_name="market-orders",
        source_url="https://example.com/market-orders-2026-01-01.csv.bz2",
    )
    writer = _FakeWriter()

    def fail_publish_sql_rows(
        sql_source: DuckLakeSqlSnapshotSource,
        *,
        data_table: RawDuckLakeTable,
        provenance_table,
        source_object_id: str,
        mode: DuckLakeWriterMode,
        row_count: int | None = None,
    ):
        writer.calls.append(("publish_sql_rows", {"sql": sql_source.sql, "table": data_table, "mode": mode}))
        raise RuntimeError("boom")

    writer.publish_source_object_sql_rows = fail_publish_sql_rows  # type: ignore[method-assign]

    with pytest.raises(SnapshotScopePublishError, match="source_object_id"):
        publish_file_backed_snapshot_rows(
            result,
            writer,
            source_system="everef",
            endpoint="market_orders",
            source_market_date=date(2026, 1, 1),
            snapshot_ts=datetime(2026, 1, 1, tzinfo=UTC),
            table_key=RawDuckLakeTable.MARKET_ORDERS,
            sql_source=DuckLakeSqlSnapshotSource(sql="select 1"),
        )

    assert [call[0] for call in writer.calls] == [
        "source_object_ingested_sha256",
        "record",
        "source_object_ingested_sha256",
        "publish_sql_rows",
    ]
    assert "mark_failed" not in [call[0] for call in writer.calls]


def test_publish_file_backed_market_order_rows_does_not_retry_replace_table_conflict(monkeypatch) -> None:
    result = make_cache_result(
        "/tmp/market-orders-2026-01-01.csv.bz2",
        dataset_name="market-orders",
        source_url="https://example.com/market-orders-2026-01-01.csv.bz2",
    )
    writer = _FakeWriter()
    writer.transaction_exit_exceptions = [RuntimeError("ducklake_snapshot primary key constraint violation")]
    parsed_table = pa.table({"order_id": [1], "price": [10.0]})
    sleep_calls: list[float] = []

    monkeypatch.setattr(csv_reader.time, "sleep", sleep_calls.append)

    outcome = publish_file_backed_rows(
        result,
        writer,
        source_system="everef",
        endpoint="market_orders",
        source_market_date=date(2026, 1, 1),
        table_key=RawDuckLakeTable.MARKET_ORDERS,
        mode=DuckLakeWriterMode.REPLACE_TABLE,
        key_columns=[],
        parse_table=lambda _: parsed_table,
    )

    assert outcome.success is False
    assert [call[0] for call in writer.calls] == [
        "record",
        "transaction_enter",
        "mark_parsed",
        "publish_rows",
        "mark_ingested",
        "transaction_commit_error",
        "mark_failed",
    ]
    assert sleep_calls == []


def test_parse_last_modified_timestamp_supports_iso_and_http_date() -> None:
    iso_value = parse_last_modified_timestamp("2026-01-02T11:01:55Z")
    http_value = parse_last_modified_timestamp("Fri, 02 Jan 2026 11:01:55 GMT")

    assert iso_value == http_value


def test_parse_last_modified_timestamp_returns_none_for_invalid_value(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("eve_ingest.sources.everef")
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=logger.name):
            value = parse_last_modified_timestamp("not-a-timestamp")
            assert value is None
            assert "Could not parse last_modified timestamp" in caplog.text
    finally:
        logger.removeHandler(caplog.handler)
