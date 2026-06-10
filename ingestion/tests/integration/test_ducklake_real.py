from __future__ import annotations

from datetime import date

import duckdb
import pyarrow as pa
import pytest

from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig
from eve_ingest.ducklake.bootstrap import bootstrap_raw_ducklake
from eve_ingest.ducklake.locks import DuckLakeLockToken, ducklake_lock_domains_for_tables
from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.ducklake.raw_publish import RawTablePublisher
from eve_ingest.ducklake.session import DuckLakeSession


class _KeepConnection:
    """Wraps a real DuckDB connection, ignoring close().

    Lets the connection survive multiple DuckLakeSession with-blocks
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
    monkeypatch.setattr("eve_ingest.ducklake.session.duckdb.connect", lambda: con)
    monkeypatch.setattr("eve_ingest.ducklake.bootstrap.duckdb.connect", lambda: con)
    monkeypatch.setattr(
        "eve_ingest.ducklake.session.DuckLakeSession._attach",
        lambda self: None,
    )
    monkeypatch.setattr(
        "eve_ingest.ducklake.bootstrap._attach_bootstrap",
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


def _test_lock_token() -> DuckLakeLockToken:
    return DuckLakeLockToken.unsafe_for_tests(
        ducklake_lock_domains_for_tables(
            data_tables=tuple(RawDuckLakeTable),
            provenance_tables=tuple(RawDuckLakeProvenanceTable),
        )
    )


@pytest.fixture(autouse=True)
def bootstrapped(shared_con) -> None:
    bootstrap_raw_ducklake(_ATTACH)


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

    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        first_metrics = raw.write(
            rows,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        )

    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
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
    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(
            table_a,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    table_b = pa.table({"type_id": [1, 2, 3], "average": [10.0, 20.0, 30.0], "source_market_date": ["2026-01-01"] * 3})
    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
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
    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(
            table_a,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    table_b = pa.table({"average": [20.0], "type_id": [2], "source_market_date": ["2026-01-02"]})
    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
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
    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(
            table_a,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
        )

    table_b = pa.table({"type_id": [1], "date": ["2026-01-02"]})
    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
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
    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(
            first,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    second = pa.table({"type_id": [1], "average": [99.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
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

    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(
            rows,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
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
    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(
            first,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    second = pa.table({"type_id": [2], "average": [20.0], "source_market_date": ["2026-01-01"]})
    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
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
    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
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
    with DuckLakeSession(_ATTACH, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(
            second,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        )

    rows = shared_con.execute(
        f'SELECT order_id, price, "source_market_date" FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY order_id'
    ).fetchall()
    assert rows == [(1, 10.0, date(2026, 1, 1)), (2, 20.0, date(2026, 1, 1))]
