from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, date, datetime

import pyarrow as pa
import pytest

from eve_ingest.ducklake.raw_tables import DuckLakeWriteMetrics, DuckLakeWriterMode, RawDuckLakeTable
from eve_ingest.sources.everef import csv_reader
from eve_ingest.sources.everef.csv_reader import publish_file_backed_rows
from eve_ingest.sources.everef.provenance import parse_last_modified_timestamp
from tests.sources.everef.conftest import make_cache_result


class _FakeWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.transaction_exit_exceptions: list[Exception | None] = []

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

    def upsert_source_object(self, data: dict, *, table) -> None:
        self.calls.append(("upsert", data.copy()))

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


def test_publish_file_backed_rows_groups_write_and_success_provenance_after_initial_upsert() -> None:
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
        "upsert",
        "transaction_enter",
        "upsert",
        "write",
        "upsert",
        "transaction_commit",
    ]
    assert writer.calls[1][0] == "transaction_enter"
    assert writer.calls[2][1]["status"] == "parsed"
    assert writer.calls[3][1]["columns"] == ("type_id", "average", "source_object_id", "source_market_date")
    assert writer.calls[4][1]["status"] == "ingested"


def test_publish_file_backed_rows_marks_failure_after_transaction_rollback() -> None:
    result = make_cache_result(
        "/tmp/market-orders-2026-01-01.csv.bz2",
        dataset_name="market-orders",
        source_url="https://example.com/market-orders-2026-01-01.csv.bz2",
    )
    writer = _FakeWriter()
    parsed_table = pa.table({"order_id": [1], "price": [10.0]})

    def fail_write(
        arrow_table: pa.Table,
        *,
        table: RawDuckLakeTable,
        mode: DuckLakeWriterMode,
        key_columns: list[str],
    ):
        writer.calls.append(("write", {"rows": len(arrow_table)}))
        raise RuntimeError("boom")

    writer.write = fail_write  # type: ignore[method-assign]

    outcome = publish_file_backed_rows(
        result,
        writer,
        source_system="everef",
        endpoint="market_orders",
        source_market_date=date(2026, 1, 1),
        table_key=RawDuckLakeTable.MARKET_ORDERS,
        mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
        key_columns=["order_id"],
        parse_table=lambda _: parsed_table,
        snapshot_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert outcome.success is False
    assert [call[0] for call in writer.calls] == [
        "upsert",
        "transaction_enter",
        "upsert",
        "write",
        "transaction_rollback",
        "upsert",
    ]
    assert writer.calls[-1][1]["status"] == "failed"
    assert writer.calls[-1][1]["status_reason"] == "see log for details"


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
        mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
        key_columns=["order_id"],
        parse_table=lambda _: parsed_table,
        snapshot_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert outcome.success is True
    assert [call[0] for call in writer.calls] == [
        "upsert",
        "transaction_enter",
        "upsert",
        "write",
        "upsert",
        "transaction_commit_error",
        "transaction_enter",
        "upsert",
        "write",
        "upsert",
        "transaction_commit",
    ]
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
        mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
        key_columns=["order_id"],
        parse_table=lambda _: parsed_table,
        snapshot_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert outcome.success is False
    assert [call[0] for call in writer.calls] == [
        "upsert",
        "transaction_enter",
        "upsert",
        "write",
        "upsert",
        "transaction_commit_error",
        "upsert",
    ]
    assert sleep_calls == []


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
        "upsert",
        "transaction_enter",
        "upsert",
        "write",
        "upsert",
        "transaction_commit_error",
        "upsert",
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
