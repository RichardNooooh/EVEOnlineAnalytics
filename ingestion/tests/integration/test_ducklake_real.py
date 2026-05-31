from __future__ import annotations

import duckdb
import pyarrow as pa
import pytest

from ingest.publishers.ducklake import (
    DuckLakeAttachConfig,
    DuckLakeWriter,
    DuckLakeWriterMode,
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
        writer.write(
            table_a,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["id"],
        )

    table_b = pa.table({"id": [2, 3], "value": [20, 30]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            table_b,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["id"],
        )

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
        writer.write(
            table_a,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["a"],
        )

    table_b = pa.table({"b": ["y"], "a": [2]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            table_b,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["a"],
        )

    result = shared_con.execute(
        f'SELECT a, b FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY a'
    ).fetchall()

    assert result == [
        (1, "x"),
        (2, "y"),
    ]


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_replace_table_overwrites_existing_rows(shared_con):
    table_a = pa.table({"id": [1], "value": [10]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            table_a,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
        )

    table_b = pa.table({"id": [1], "value": [99]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            table_b,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
        )

    result = shared_con.execute(
        f'SELECT id, value FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY id'
    ).fetchall()

    assert result == [(1, 99)]


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_merge_raises_for_matching_key_with_different_values(shared_con):
    first = pa.table({"id": [1], "value": [10], "_source_market_date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            first,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["id"],
        )

    second = pa.table({"id": [1], "value": [99], "_source_market_date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        with pytest.raises(ValueError, match="differing values"):
            writer.write(
                second,
                table=RawDuckLakeTable.MARKET_ORDERS,
                mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
                key_columns=["id"],
            )

    rows = shared_con.execute(
        f'SELECT id, value FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY id'
    ).fetchall()
    assert rows == [(1, 10)]


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_insert_missing_keys_is_idempotent_for_identical_snapshot(shared_con):
    rows = pa.table({"id": [1], "value": [10], "_source_market_date": ["2026-01-01"]})

    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            rows,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["id"],
        )

    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            rows,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["id"],
        )

    result = shared_con.execute(
        f'SELECT id, value FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY id'
    ).fetchall()
    assert result == [(1, 10)]


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_authoritative_mode_raises_when_target_has_source_date_rows_missing_from_source(shared_con):
    first = pa.table({"id": [1], "value": [10], "_source_market_date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            first,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["id"],
        )

    second = pa.table({"id": [2], "value": [20], "_source_market_date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        with pytest.raises(ValueError, match="source_date"):
            writer.write(
                second,
                table=RawDuckLakeTable.MARKET_HISTORY,
                mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
                key_columns=["id"],
            )

    rows = shared_con.execute(
        f'SELECT id, value, "_source_market_date" FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY id'
    ).fetchall()
    assert rows == [(1, 10, "2026-01-01")]


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_insert_missing_keys_allows_partial_source_date_coverage(shared_con):
    first = pa.table({"id": [1], "value": [10], "_source_market_date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            first,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["id"],
        )

    second = pa.table({"id": [2], "value": [20], "_source_market_date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            second,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["id"],
        )

    rows = shared_con.execute(
        f'SELECT id, value, "_source_market_date" FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY id'
    ).fetchall()
    assert rows == [(1, 10, "2026-01-01"), (2, 20, "2026-01-01")]
