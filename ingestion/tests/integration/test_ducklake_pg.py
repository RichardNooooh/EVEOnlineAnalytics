from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import duckdb
import pyarrow as pa
import pytest

from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig, build_ducklake_attach_config_from_url
from eve_ingest.ducklake.locks import DuckLakeLockToken, ducklake_lock_domains_for_tables
from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.ducklake.writer import DuckLakeWriter, _attach, _ident, bootstrap_raw_ducklake


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
    con = duckdb.connect()
    _attach(con, config=attach_config)
    return con


def _drop_table(con: duckdb.DuckDBPyConnection, attach_config: DuckLakeAttachConfig, table: RawDuckLakeTable) -> None:
    alias = _ident(attach_config.alias)
    con.execute(f"DROP TABLE IF EXISTS {alias}.raw.{_ident(table.value)}")


def _test_lock_token() -> DuckLakeLockToken:
    return DuckLakeLockToken.unsafe_for_tests(
        ducklake_lock_domains_for_tables(
            data_tables=tuple(RawDuckLakeTable),
            provenance_tables=tuple(RawDuckLakeProvenanceTable),
        )
    )


@pytest.mark.integration
def test_ducklake_writer_attaches_to_postgres(attach_config: DuckLakeAttachConfig) -> None:
    with DuckLakeWriter(attach_config):
        pass


@pytest.mark.integration
def test_replace_table_writes_rows(attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection) -> None:
    bootstrap_raw_ducklake(attach_config)

    table = pa.table({"type_id": [34, 35], "date": ["2026-01-01", "2026-01-02"]})
    with DuckLakeWriter(attach_config, lock_token=_test_lock_token()) as writer:
        writer.write(table, table=RawDuckLakeTable.MARKET_HISTORY, mode=DuckLakeWriterMode.REPLACE_TABLE)

    rows = raw_con.execute(
        f'SELECT type_id, "date" FROM {_ident(attach_config.alias)}.raw.raw_market_history ORDER BY type_id'
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] == (34, date(2026, 1, 1))
    assert rows[1] == (35, date(2026, 1, 2))


@pytest.mark.integration
def test_write_with_key_columns_does_insert_if_not_exists(
    attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection
) -> None:
    bootstrap_raw_ducklake(attach_config)

    table = pa.table({"order_id": [1, 2], "price": [100.0, 200.0]})
    with DuckLakeWriter(attach_config, lock_token=_test_lock_token()) as writer:
        writer.write(
            table,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    # Insert same order_ids again with identical prices — should be no-ops
    duplicate = pa.table({"order_id": [1, 2], "price": [100.0, 200.0]})
    with DuckLakeWriter(attach_config, lock_token=_test_lock_token()) as writer:
        writer.write(
            duplicate,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    rows = raw_con.execute(
        f"SELECT order_id, price FROM {_ident(attach_config.alias)}.raw.raw_market_orders ORDER BY order_id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] == (1, 100.0)
    assert rows[1] == (2, 200.0)


@pytest.mark.integration
def test_publish_arrow_table_one_shot(attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection) -> None:
    bootstrap_raw_ducklake(attach_config)

    table = pa.table({"type_id": [42], "date": ["2026-06-01"]})
    with DuckLakeWriter(attach_config, lock_token=_test_lock_token()) as writer:
        writer.write(
            table,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    rows = raw_con.execute(
        f"SELECT * FROM {_ident(attach_config.alias)}.raw.raw_market_history WHERE type_id = 42"
    ).fetchall()
    assert len(rows) == 1


@pytest.mark.integration
def test_written_data_queryable_through_duckdb(
    attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection
) -> None:
    bootstrap_raw_ducklake(attach_config)

    table = pa.table({"type_id": [1, 2, 3], "date": ["2026-01-01"] * 3})
    with DuckLakeWriter(attach_config, lock_token=_test_lock_token()) as writer:
        writer.write(table, table=RawDuckLakeTable.MARKET_HISTORY, mode=DuckLakeWriterMode.REPLACE_TABLE)

    count = raw_con.execute(f"SELECT count(*) FROM {_ident(attach_config.alias)}.raw.raw_market_history").fetchone()[0]
    assert count == 3


@pytest.mark.integration
def test_insert_style_write_fails_when_bootstrapped_table_is_missing(
    attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection
) -> None:
    bootstrap_raw_ducklake(attach_config)
    _drop_table(raw_con, attach_config, RawDuckLakeTable.MARKET_ORDERS)

    table = pa.table({"order_id": [1], "price": [100.0]})
    with DuckLakeWriter(attach_config, lock_token=_test_lock_token()) as writer:
        with pytest.raises(RuntimeError, match="eve-ingest ducklake bootstrap raw"):
            writer.write(
                table,
                table=RawDuckLakeTable.MARKET_ORDERS,
                mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
                key_columns=["order_id"],
            )


@pytest.mark.integration
def test_bootstrap_creates_raw_schema_data_tables_and_provenance_tables(
    attach_config: DuckLakeAttachConfig,
) -> None:
    bootstrap_raw_ducklake(attach_config)
    con = duckdb.connect()
    _attach(con, config=attach_config)
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
