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
def test_merge_inserts_new_rows_and_skips_existing(shared_con):
    """Verify MERGE inserts new key rows and skips existing key rows.

    Uses a real in-memory DuckDB to validate SQL correctness.
    """
    table_a = pa.table({"type_id": [1, 2], "average": [10.0, 20.0], "source_market_date": ["2026-01-01"] * 2})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            table_a,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    table_b = pa.table({"type_id": [1, 2, 3], "average": [10.0, 20.0, 30.0], "source_market_date": ["2026-01-01"] * 3})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            table_b,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    result = shared_con.execute(
        f'SELECT type_id, average FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY type_id'
    ).fetchall()

    assert result == [
        (1, 10.0),
        (2, 20.0),
        (3, 30.0),
    ], f"Expected 3 rows with correct values, got {result}"


@pytest.mark.real_duckdb
def test_merge_column_order_independent(shared_con):
    """Verify BY NAME matching means column order doesn't matter."""
    table_a = pa.table({"type_id": [1], "average": [10.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            table_a,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    table_b = pa.table({"average": [20.0], "type_id": [2], "source_market_date": ["2026-01-02"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            table_b,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
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
def test_merge_raises_for_matching_key_with_different_values(shared_con):
    first = pa.table({"type_id": [1], "average": [10.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            first,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    second = pa.table({"type_id": [1], "average": [99.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        with pytest.raises(ValueError, match="differing values"):
            raw.write(
                second,
                table=RawDuckLakeTable.MARKET_HISTORY,
                mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
                key_columns=["type_id"],
            )

    rows = shared_con.execute(
        f'SELECT type_id, average FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY type_id'
    ).fetchall()
    assert rows == [(1, 10.0)]


@pytest.mark.real_duckdb
def test_authoritative_mode_is_idempotent_for_identical_source_date(shared_con):
    rows = pa.table({"type_id": [1], "average": [10.0], "source_market_date": ["2026-01-01"]})

    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            rows,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            rows,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    result = shared_con.execute(
        f'SELECT type_id, average FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY type_id'
    ).fetchall()
    assert result == [(1, 10.0)]


@pytest.mark.real_duckdb
def test_authoritative_mode_raises_when_target_has_source_date_rows_missing_from_source(shared_con):
    first = pa.table({"type_id": [1], "average": [10.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        raw.write(
            first,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    second = pa.table({"type_id": [2], "average": [20.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeSession(ATTACH, lock_token=create_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=create_lock_token())
        with pytest.raises(ValueError, match="source_date"):
            raw.write(
                second,
                table=RawDuckLakeTable.MARKET_HISTORY,
                mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
                key_columns=["type_id"],
            )

    rows = shared_con.execute(
        f'SELECT type_id, average, "source_market_date" FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}" ORDER BY type_id'
    ).fetchall()
    assert rows == [(1, 10.0, date(2026, 1, 1))]


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
