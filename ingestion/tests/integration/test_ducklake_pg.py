from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import duckdb
import pyarrow as pa
import pytest

from ingest.publishers.ducklake import (
    _attach_ducklake,
    _quote_identifier,
    DuckLakeAttachConfig,
    DuckLakeWriter,
    DuckLakeWriterMode,
    RawDuckLakeTable,
    build_ducklake_attach_config_from_url,
)


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
    _attach_ducklake(con, config=attach_config)
    return con


def _drop_table(con: duckdb.DuckDBPyConnection, attach_config: DuckLakeAttachConfig, table: RawDuckLakeTable) -> None:
    alias = _quote_identifier(attach_config.alias)
    con.execute(f"DROP TABLE IF EXISTS {alias}.raw.{_quote_identifier(table.value)}")


@pytest.mark.integration
def test_ducklake_writer_attaches_to_postgres(attach_config: DuckLakeAttachConfig) -> None:
    with DuckLakeWriter(attach_config):
        pass


@pytest.mark.integration
def test_replace_table_writes_rows(attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection) -> None:
    _drop_table(raw_con, attach_config, RawDuckLakeTable.MARKET_HISTORY)

    table = pa.table({"type_id": [34, 35], "date": ["2026-01-01", "2026-01-02"]})
    with DuckLakeWriter(attach_config) as writer:
        writer.write(table, table=RawDuckLakeTable.MARKET_HISTORY, mode=DuckLakeWriterMode.REPLACE_TABLE)

    rows = raw_con.execute(
        f"SELECT * FROM {_quote_identifier(attach_config.alias)}.raw.raw_market_history ORDER BY type_id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] == (34, "2026-01-01")
    assert rows[1] == (35, "2026-01-02")


@pytest.mark.integration
def test_write_with_key_columns_does_insert_if_not_exists(
    attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection
) -> None:
    _drop_table(raw_con, attach_config, RawDuckLakeTable.MARKET_ORDERS)

    table = pa.table({"order_id": [1, 2], "price": [100.0, 200.0]})
    with DuckLakeWriter(attach_config) as writer:
        writer.write(
            table,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    # Insert same order_ids again with identical prices — should be no-ops
    duplicate = pa.table({"order_id": [1, 2], "price": [100.0, 200.0]})
    with DuckLakeWriter(attach_config) as writer:
        writer.write(
            duplicate,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    rows = raw_con.execute(
        f"SELECT * FROM {_quote_identifier(attach_config.alias)}.raw.raw_market_orders ORDER BY order_id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] == (1, 100.0)
    assert rows[1] == (2, 200.0)


@pytest.mark.integration
def test_publish_arrow_table_one_shot(attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection) -> None:
    _drop_table(raw_con, attach_config, RawDuckLakeTable.MARKET_HISTORY)

    table = pa.table({"type_id": [42], "date": ["2026-06-01"]})
    with DuckLakeWriter(attach_config) as writer:
        writer.write(
            table,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )

    rows = raw_con.execute(
        f"SELECT * FROM {_quote_identifier(attach_config.alias)}.raw.raw_market_history WHERE type_id = 42"
    ).fetchall()
    assert len(rows) == 1


@pytest.mark.integration
def test_written_data_queryable_through_duckdb(
    attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection
) -> None:
    _drop_table(raw_con, attach_config, RawDuckLakeTable.MARKET_HISTORY)

    table = pa.table({"type_id": [1, 2, 3], "date": ["2026-01-01"] * 3})
    with DuckLakeWriter(attach_config) as writer:
        writer.write(table, table=RawDuckLakeTable.MARKET_HISTORY, mode=DuckLakeWriterMode.REPLACE_TABLE)

    count = raw_con.execute(
        f"SELECT count(*) FROM {_quote_identifier(attach_config.alias)}.raw.raw_market_history"
    ).fetchone()[0]
    assert count == 3


@pytest.mark.integration
def test_write_auto_creates_schema_and_table(
    attach_config: DuckLakeAttachConfig,
) -> None:
    """write() should succeed with no pre-existing schema or table."""
    table = pa.table({"type_id": [1, 2, 3], "date": ["2026-01-01"] * 3})
    with DuckLakeWriter(attach_config) as writer:
        writer.write(table, table=RawDuckLakeTable.MARKET_HISTORY, mode=DuckLakeWriterMode.REPLACE_TABLE)

    con = duckdb.connect()
    _attach_ducklake(con, config=attach_config)
    rows = con.execute(
        f"SELECT * FROM {_quote_identifier(attach_config.alias)}.raw.raw_market_history ORDER BY type_id"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0] == (1, "2026-01-01")
