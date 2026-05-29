from __future__ import annotations

import logging

import duckdb
import pyarrow as pa
import pytest

from ingest.publishers.ducklake import (
    DuckLakeAttachConfig,
    DuckLakeWriter,
    RawDuckLakeTable,
)


class _KeepConnection:
    """Wraps a real DuckDB connection, ignoring close().

    Lets the connection survive multiple DuckLakeWriter with-blocks
    so later blocks see the same in-memory data.
    """

    def __init__(self) -> None:
        self._con = duckdb.connect(":memory:")

    def __getattr__(self, name: str):
        return getattr(self._con, name)

    def close(self) -> None:
        pass


@pytest.fixture
def shared_con(monkeypatch):
    """Real in-memory DuckDB connection that is NOT closed on writer exit."""
    con = _KeepConnection()
    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)
    monkeypatch.setattr(
        "ingest.publishers.ducklake._attach_ducklake",
        lambda c, config: None,
    )
    yield con._con
    con._con.close()


_ATTACH = DuckLakeAttachConfig(
    attach_uri=":memory:",
    data_path="",
    metadata_schema="memory",
    alias="memory",
)


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_merge_inserts_new_rows_and_skips_existing(shared_con):
    """Verify MERGE inserts new key rows and skips existing key rows.

    Uses a real in-memory DuckDB to validate SQL correctness.
    """
    table_a = pa.table({"id": [1, 2], "value": [10, 20]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(table_a, table=RawDuckLakeTable.MARKET_ORDERS, key_columns=["id"])

    table_b = pa.table({"id": [2, 3], "value": [99, 30]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(table_b, table=RawDuckLakeTable.MARKET_ORDERS, key_columns=["id"])

    result = shared_con.execute(
        f'SELECT id, value FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY id'
    ).fetchall()

    assert result == [
        (1, 10),
        (2, 20),
        (3, 30),
    ], f"Expected 3 rows with correct values, got {result}"


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_merge_column_order_independent(shared_con):
    """Verify BY NAME matching means column order doesn't matter."""
    table_a = pa.table({"a": [1], "b": ["x"]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(table_a, table=RawDuckLakeTable.MARKET_ORDERS, key_columns=["a"])

    table_b = pa.table({"b": ["y"], "a": [2]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(table_b, table=RawDuckLakeTable.MARKET_ORDERS, key_columns=["a"])

    result = shared_con.execute(
        f'SELECT a, b FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY a'
    ).fetchall()

    assert result == [
        (1, "x"),
        (2, "y"),
    ]


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_append_without_key_columns(shared_con):
    """Without key_columns, rows should always be appended (no merge)."""
    table_a = pa.table({"id": [1], "value": [10]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(table_a, table=RawDuckLakeTable.MARKET_HISTORY)

    table_b = pa.table({"id": [1], "value": [99]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(table_b, table=RawDuckLakeTable.MARKET_HISTORY)

    result = shared_con.execute(
        f'SELECT id, value FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY id'
    ).fetchall()

    assert result == [
        (1, 10),
        (1, 99),
    ]


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_merge_logs_warning_for_matching_key_with_different_values(shared_con, caplog):
    caplog.set_level(logging.WARNING, logger="ingest.publishers")

    first = pa.table({"id": [1], "value": [10]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(first, table=RawDuckLakeTable.MARKET_ORDERS, key_columns=["id"])

    caplog.clear()

    second = pa.table({"id": [1], "value": [99]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(second, table=RawDuckLakeTable.MARKET_ORDERS, key_columns=["id"])

    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "WARNING"
    assert "Matched key" in caplog.text

    rows = shared_con.execute(
        f'SELECT id, value FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY id'
    ).fetchall()
    assert rows == [(1, 10)]
