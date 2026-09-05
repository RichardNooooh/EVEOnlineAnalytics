from __future__ import annotations

from datetime import date

import pyarrow as pa
import pytest
from eve_ingest.ducklake.raw_publish import RawTablePublisher
from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeTable
from eve_ingest.ducklake.session import DuckLakeSession

from .conftest import ATTACH, create_lock_token


@pytest.mark.real_duckdb
def test_append_snapshot_rows_appends_duplicate_snapshot_rows(shared_con):
    rows = pa.table(
        {
            "order_id": [1],
            "price": [10.0],
            "source_ref_id": ["soid-1"],
            "source_market_date": [date(2026, 1, 1)],
            "snapshot_ts": ["2026-01-01"],
        }
    )

    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        first_metrics = raw.write(
            rows,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        )

    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        second_metrics = raw.write(
            rows,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        )

    result = shared_con.execute(
        f'SELECT order_id, price FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY order_id'
    ).fetchall()
    assert result == [(1, 10.0), (1, 10.0)]
    assert first_metrics.inserted_rows == 1
    assert first_metrics.matched_rows == 0
    assert second_metrics.inserted_rows == 1
    assert second_metrics.matched_rows == 0


@pytest.mark.real_duckdb
def test_partition_replacement_updates_one_partition(shared_con):
    """Verify replacement updates one partition without affecting another.

    Uses a real in-memory DuckDB to validate SQL correctness.
    """
    table_a = pa.table({"type_id": [1, 2], "average": [10.0, 20.0], "source_market_date": ["2026-01-01"] * 2})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            table_a,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_PARTITION,
            key_columns=["type_id"],
            partition_column="source_market_date",
            partition_value="2026-01-01",
        )

    table_b = pa.table({"type_id": [2, 3], "average": [22.0, 30.0], "source_market_date": ["2026-01-01"] * 2})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            table_b,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_PARTITION,
            key_columns=["type_id"],
            partition_column="source_market_date",
            partition_value="2026-01-01",
        )

    result = shared_con.execute(
        f'SELECT type_id, average FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY type_id'
    ).fetchall()

    assert result == [
        (2, 22.0),
        (3, 30.0),
    ], f"Expected replacement rows with correct values, got {result}"


@pytest.mark.real_duckdb
def test_merge_column_order_independent(shared_con):
    """Verify BY NAME matching means column order doesn't matter."""
    table_a = pa.table({"type_id": [1], "average": [10.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            table_a,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_PARTITION,
            key_columns=["type_id"],
            partition_column="source_market_date",
            partition_value="2026-01-01",
        )

    table_b = pa.table({"average": [20.0], "type_id": [2], "source_market_date": ["2026-01-02"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            table_b,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_PARTITION,
            key_columns=["type_id"],
            partition_column="source_market_date",
            partition_value="2026-01-02",
        )

    result = shared_con.execute(
        f'SELECT type_id, average FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY type_id'
    ).fetchall()

    assert result == [
        (1, 10.0),
        (2, 20.0),
    ]


@pytest.mark.real_duckdb
def test_replace_table_overwrites_existing_rows(shared_con):
    table_a = pa.table({"type_id": [1], "date": ["2026-01-01"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            table_a,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
        )

    table_b = pa.table({"type_id": [1], "date": ["2026-01-02"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            table_b,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
        )

    result = shared_con.execute(
        f'SELECT type_id, "date" FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY type_id'
    ).fetchall()

    assert result == [(1, date(2026, 1, 2))]


@pytest.mark.real_duckdb
def test_partition_replacement_accepts_matching_key_with_different_values(shared_con):
    first = pa.table({"type_id": [1], "average": [10.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            first,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_PARTITION,
            key_columns=["type_id"],
            partition_column="source_market_date",
            partition_value="2026-01-01",
        )

    second = pa.table({"type_id": [1], "average": [99.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            second,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_PARTITION,
            key_columns=["type_id"],
            partition_column="source_market_date",
            partition_value="2026-01-01",
        )

    rows = shared_con.execute(
        f'SELECT type_id, average FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY type_id'
    ).fetchall()
    assert rows == [(1, 99.0)]


@pytest.mark.real_duckdb
def test_authoritative_mode_is_idempotent_for_identical_source_date(shared_con):
    rows = pa.table({"type_id": [1], "average": [10.0], "source_market_date": ["2026-01-01"]})

    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            rows,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_PARTITION,
            key_columns=["type_id"],
            partition_column="source_market_date",
            partition_value="2026-01-01",
        )

    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            rows,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_PARTITION,
            key_columns=["type_id"],
            partition_column="source_market_date",
            partition_value="2026-01-01",
        )

    result = shared_con.execute(
        f'SELECT type_id, average FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY type_id'
    ).fetchall()
    assert result == [(1, 10.0)]


@pytest.mark.real_duckdb
def test_authoritative_mode_replaces_rows_missing_from_new_source(shared_con):
    first = pa.table({"type_id": [1], "average": [10.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            first,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_PARTITION,
            key_columns=["type_id"],
            partition_column="source_market_date",
            partition_value="2026-01-01",
        )

    second = pa.table({"type_id": [2], "average": [20.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            second,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_PARTITION,
            key_columns=["type_id"],
            partition_column="source_market_date",
            partition_value="2026-01-01",
        )

    rows = shared_con.execute(
        f'SELECT type_id, average, "source_market_date" FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY type_id'
    ).fetchall()
    assert rows == [(2, 20.0, date(2026, 1, 1))]


@pytest.mark.real_duckdb
def test_partition_replacement_rejects_rows_outside_expected_partition(shared_con):
    rows = pa.table({"type_id": [1], "average": [10.0], "source_market_date": ["2026-01-02"]})

    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        with pytest.raises(ValueError, match="outside the expected partition"):
            raw.write(
                rows,
                table=RawDuckLakeTable.MARKET_HISTORY,
                mode=DuckLakeWriterMode.REPLACE_PARTITION,
                key_columns=["type_id"],
                partition_column="source_market_date",
                partition_value="2026-01-01",
            )

    count = shared_con.execute(
        f'SELECT COUNT(*) FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}"'
    ).fetchone()
    assert count == (0,)


@pytest.mark.real_duckdb
def test_partition_replacement_rejects_duplicate_keys(shared_con):
    rows = pa.table(
        {
            "type_id": [1, 1],
            "average": [10.0, 11.0],
            "source_market_date": ["2026-01-01", "2026-01-01"],
        }
    )

    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        with pytest.raises(ValueError, match="duplicate keys: type_id=1"):
            raw.write(
                rows,
                table=RawDuckLakeTable.MARKET_HISTORY,
                mode=DuckLakeWriterMode.REPLACE_PARTITION,
                key_columns=["type_id"],
                partition_column="source_market_date",
                partition_value="2026-01-01",
            )

    count = shared_con.execute(
        f'SELECT COUNT(*) FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}"'
    ).fetchone()
    assert count == (0,)


@pytest.mark.real_duckdb
def test_empty_authoritative_partition_removes_existing_rows(shared_con):
    initial = pa.table({"type_id": [1], "average": [10.0], "source_market_date": ["2026-01-01"]})
    empty = pa.table(
        {
            "type_id": pa.array([], type=pa.int64()),
            "average": pa.array([], type=pa.float64()),
            "source_market_date": pa.array([], type=pa.string()),
        }
    )

    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            initial,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_PARTITION,
            key_columns=["type_id"],
            partition_column="source_market_date",
            partition_value="2026-01-01",
        )

    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        metrics = raw.write(
            empty,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_PARTITION,
            key_columns=["type_id"],
            partition_column="source_market_date",
            partition_value="2026-01-01",
        )

    count = shared_con.execute(
        f'SELECT COUNT(*) FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}"'
    ).fetchone()
    assert count == (0,)
    assert metrics.inserted_rows == 0
    assert metrics.replaced_rows == 1


@pytest.mark.real_duckdb
def test_append_snapshot_rows_allows_partial_source_date_coverage(shared_con):
    first = pa.table(
        {
            "order_id": [1],
            "price": [10.0],
            "source_ref_id": ["soid-1"],
            "source_market_date": ["2026-01-01"],
            "snapshot_ts": ["2026-01-01"],
        }
    )
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            first,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        )

    second = pa.table(
        {
            "order_id": [2],
            "price": [20.0],
            "source_ref_id": ["soid-2"],
            "source_market_date": ["2026-01-01"],
            "snapshot_ts": ["2026-01-01"],
        }
    )
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            second,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        )

    rows = shared_con.execute(
        f'SELECT order_id, price, "source_market_date" FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY order_id'
    ).fetchall()
    assert rows == [(1, 10.0, date(2026, 1, 1)), (2, 20.0, date(2026, 1, 1))]
