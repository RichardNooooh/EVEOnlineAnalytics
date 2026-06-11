from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import duckdb
import pyarrow as pa
import pytest

from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig, build_ducklake_attach_config_from_url
from eve_ingest.ducklake.bootstrap import bootstrap_raw_ducklake
from eve_ingest.ducklake.locks import DuckLakeLockToken, ducklake_lock_domains_for_tables
from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.ducklake.session import DuckLakeSession
from eve_ingest.ducklake.sql import quote_identifier
from eve_ingest.ducklake.raw_publish import RawTablePublisher


@pytest.fixture
def attach_config(pg_url: str, tmp_path: Path) -> DuckLakeAttachConfig:
    data_path = str(tmp_path / "ducklake")
    suffix = uuid4().hex
    return build_ducklake_attach_config_from_url(
        pg_url,
        data_path=data_path,
        metadata_schema=f"test_{suffix}",
        alias=f"ducklake_{suffix}",
    )


@pytest.fixture
def raw_con(attach_config: DuckLakeAttachConfig) -> duckdb.DuckDBPyConnection:
    session = DuckLakeSession(attach_config)
    session.__enter__()
    return session.connection


def _drop_table(con: duckdb.DuckDBPyConnection, attach_config: DuckLakeAttachConfig, table: RawDuckLakeTable) -> None:
    alias = quote_identifier(attach_config.alias)
    con.execute(f"DROP TABLE IF EXISTS {alias}.raw.{quote_identifier(table.value)}")


def _test_lock_token() -> DuckLakeLockToken:
    return DuckLakeLockToken.unsafe_for_tests(
        ducklake_lock_domains_for_tables(
            data_tables=tuple(RawDuckLakeTable),
            provenance_tables=tuple(RawDuckLakeProvenanceTable),
        )
    )


@pytest.mark.integration
def test_ducklake_writer_attaches_to_postgres(attach_config: DuckLakeAttachConfig) -> None:
    with DuckLakeSession(attach_config):
        pass


@pytest.mark.integration
def test_replace_table_writes_rows(attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection) -> None:
    bootstrap_raw_ducklake(attach_config)

    table = pa.table({"type_id": [34, 35], "date": ["2026-01-01", "2026-01-02"]})
    with DuckLakeSession(attach_config, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(table, table=RawDuckLakeTable.MARKET_HISTORY, mode=DuckLakeWriterMode.REPLACE_TABLE)

    rows = raw_con.execute(
        f'SELECT type_id, "date" FROM {quote_identifier(attach_config.alias)}.raw.raw_market_history ORDER BY type_id'
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] == (34, date(2026, 1, 1))
    assert rows[1] == (35, date(2026, 1, 2))


@pytest.mark.integration
def test_write_with_key_columns_does_insert_if_not_exists(
    attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection
) -> None:
    bootstrap_raw_ducklake(attach_config)

    table = pa.table({"type_id": [1, 2], "average": [100.0, 200.0], "source_market_date": ["2026-01-01"] * 2})
    with DuckLakeSession(attach_config, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(
            table,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    # Insert same order_ids again with identical prices — should be no-ops
    duplicate = pa.table({"type_id": [1, 2], "average": [100.0, 200.0], "source_market_date": ["2026-01-01"] * 2})
    with DuckLakeSession(attach_config, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(
            duplicate,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    rows = raw_con.execute(
        f"SELECT type_id, average FROM {quote_identifier(attach_config.alias)}.raw.raw_market_history ORDER BY type_id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] == (1, 100.0)
    assert rows[1] == (2, 200.0)


@pytest.mark.integration
def test_authoritative_mode_writes_new_market_history_row(
    attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection
) -> None:
    bootstrap_raw_ducklake(attach_config)

    table = pa.table({"type_id": [42], "date": ["2026-06-01"]})
    with DuckLakeSession(attach_config, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(
            table,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    rows = raw_con.execute(
        f"SELECT * FROM {quote_identifier(attach_config.alias)}.raw.raw_market_history WHERE type_id = 42"
    ).fetchall()
    assert len(rows) == 1


@pytest.mark.integration
def test_replace_table_rows_are_queryable_through_attached_duckdb(
    attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection
) -> None:
    bootstrap_raw_ducklake(attach_config)

    table = pa.table({"type_id": [1, 2, 3], "date": ["2026-01-01"] * 3})
    with DuckLakeSession(attach_config, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(table, table=RawDuckLakeTable.MARKET_HISTORY, mode=DuckLakeWriterMode.REPLACE_TABLE)

    count = raw_con.execute(
        f"SELECT count(*) FROM {quote_identifier(attach_config.alias)}.raw.raw_market_history"
    ).fetchone()[0]  # ty: ignore[not-subscriptable]
    assert count == 3


@pytest.mark.integration
def test_insert_style_write_fails_when_bootstrapped_table_is_missing(
    attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection
) -> None:
    bootstrap_raw_ducklake(attach_config)
    _drop_table(raw_con, attach_config, RawDuckLakeTable.MARKET_ORDERS)

    table = pa.table(
        {
            "order_id": [1],
            "price": [100.0],
            "source_ref_id": ["soid-1"],
            "source_market_date": ["2026-01-01"],
            "snapshot_ts": ["2026-01-01"],
        }
    )
    with DuckLakeSession(attach_config, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        with pytest.raises(RuntimeError, match="eve-ingest ducklake bootstrap raw"):
            raw.write(
                table,
                table=RawDuckLakeTable.MARKET_ORDERS,
                mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
            )


@pytest.mark.integration
def test_bootstrap_creates_raw_schema_data_tables_and_provenance_tables(
    attach_config: DuckLakeAttachConfig,
) -> None:
    bootstrap_raw_ducklake(attach_config)
    session = DuckLakeSession(attach_config)
    session.__enter__()
    con = session.connection
    tables = {
        row[0]
        for row in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'raw'").fetchall()
    }
    assert RawDuckLakeTable.MARKET_HISTORY.value in tables
    assert RawDuckLakeTable.MARKET_ORDERS.value in tables
    assert RawDuckLakeTable.FUZZWORK_ORDERS.value in tables
    assert RawDuckLakeTable.REFERENCE_TYPES.value in tables
    assert RawDuckLakeTable.REFERENCE_REGIONS.value in tables
    assert RawDuckLakeTable.REFERENCE_GROUPS.value in tables
    assert RawDuckLakeTable.REFERENCE_CATEGORIES.value in tables
    assert RawDuckLakeTable.REFERENCE_MARKET_GROUPS.value in tables
    assert RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS.value in tables
    assert RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS.value in tables
    assert RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS.value in tables
    assert RawDuckLakeProvenanceTable.REFERENCE_OBJECTS.value in tables
