from __future__ import annotations

from datetime import date

import duckdb
import pyarrow as pa
import pytest

from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig
from eve_ingest.ducklake.writer import DuckLakeWriter, bootstrap_raw_ducklake
from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeTable


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
    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)
    monkeypatch.setattr(
        "eve_ingest.ducklake.writer._attach_ducklake",
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


@pytest.fixture(autouse=True)
def bootstrapped(shared_con) -> None:
    bootstrap_raw_ducklake(_ATTACH)


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_merge_inserts_new_rows_and_skips_existing(shared_con):
    """Verify MERGE inserts new key rows and skips existing key rows.

    Uses a real in-memory DuckDB to validate SQL correctness.
    """
    table_a = pa.table({"order_id": [1, 2], "price": [10.0, 20.0]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            table_a,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    table_b = pa.table({"order_id": [2, 3], "price": [20.0, 30.0]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            table_b,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    result = shared_con.execute(
        f'SELECT order_id, price FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY order_id'
    ).fetchall()

    assert result == [
        (1, 10.0),
        (2, 20.0),
        (3, 30.0),
    ], f"Expected 3 rows with correct values, got {result}"


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_merge_column_order_independent(shared_con):
    """Verify BY NAME matching means column order doesn't matter."""
    table_a = pa.table({"order_id": [1], "price": [10.0]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            table_a,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    table_b = pa.table({"price": [20.0], "order_id": [2]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            table_b,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    result = shared_con.execute(
        f'SELECT order_id, price FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY order_id'
    ).fetchall()

    assert result == [
        (1, 10.0),
        (2, 20.0),
    ]


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_replace_table_overwrites_existing_rows(shared_con):
    table_a = pa.table({"type_id": [1], "date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            table_a,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
        )

    table_b = pa.table({"type_id": [1], "date": ["2026-01-02"]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            table_b,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
        )

    result = shared_con.execute(
        f'SELECT type_id, "date" FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY type_id'
    ).fetchall()

    assert result == [(1, date(2026, 1, 2))]


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_merge_raises_for_matching_key_with_different_values(shared_con):
    first = pa.table({"order_id": [1], "price": [10.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            first,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    second = pa.table({"order_id": [1], "price": [99.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        with pytest.raises(ValueError, match="differing values"):
            writer.write(
                second,
                table=RawDuckLakeTable.MARKET_ORDERS,
                mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
                key_columns=["order_id"],
            )

    rows = shared_con.execute(
        f'SELECT order_id, price FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY order_id'
    ).fetchall()
    assert rows == [(1, 10.0)]


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_insert_missing_keys_is_idempotent_for_identical_snapshot(shared_con):
    rows = pa.table({"order_id": [1], "price": [10.0], "source_market_date": ["2026-01-01"]})

    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            rows,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            rows,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    result = shared_con.execute(
        f'SELECT order_id, price FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY order_id'
    ).fetchall()
    assert result == [(1, 10.0)]


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_authoritative_mode_raises_when_target_has_source_date_rows_missing_from_source(shared_con):
    first = pa.table({"type_id": [1], "average": [10.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            first,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    second = pa.table({"type_id": [2], "average": [20.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        with pytest.raises(ValueError, match="source_date"):
            writer.write(
                second,
                table=RawDuckLakeTable.MARKET_HISTORY,
                mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
                key_columns=["type_id"],
            )

    rows = shared_con.execute(
        f'SELECT type_id, average, "source_market_date" FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY type_id'
    ).fetchall()
    assert rows == [(1, 10.0, date(2026, 1, 1))]


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_insert_missing_keys_allows_partial_source_date_coverage(shared_con):
    first = pa.table({"order_id": [1], "price": [10.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            first,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    second = pa.table({"order_id": [2], "price": [20.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeWriter(_ATTACH) as writer:
        writer.write(
            second,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    rows = shared_con.execute(
        f'SELECT order_id, price, "source_market_date" FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY order_id'
    ).fetchall()
    assert rows == [(1, 10.0, date(2026, 1, 1)), (2, 20.0, date(2026, 1, 1))]
