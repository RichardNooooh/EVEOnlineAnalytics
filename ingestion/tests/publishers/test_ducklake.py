from __future__ import annotations

import pytest
import pyarrow as pa

from ingest.publishers.ducklake import (
    DEFAULT_DUCKLAKE_ALIAS,
    DEFAULT_RAW_SCHEMA,
    DuckLakeAttachConfig,
    DuckLakeWriter,
    RawDuckLakeTable,
    publish_arrow_table,
)


class FakeRelation:
    def __init__(self) -> None:
        self.view_names: list[str] = []

    def create_view(self, view_name: str) -> None:
        self.view_names.append(view_name)


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str] | None]] = []
        self.relation = FakeRelation()
        self.arrow_tables: list[pa.Table] = []
        self.closed = False
        self.raise_on_execute: str | None = None

    def execute(self, query: str, params: list[str] | None = None) -> None:
        if self.raise_on_execute is not None and self.raise_on_execute in query:
            raise RuntimeError("boom")
        self.calls.append((query, params))

    def from_arrow(self, arrow_table: pa.Table) -> FakeRelation:
        self.arrow_tables.append(arrow_table)
        return self.relation

    def close(self) -> None:
        self.closed = True


def _queries(con: FakeConnection) -> list[str]:
    return [query for query, _ in con.calls]


def _attach_call(con: FakeConnection) -> tuple[str, list[str] | None]:
    for call in con.calls:
        if "ATTACH " in call[0]:
            return call
    raise AssertionError("no ATTACH call found")


def test_writer_attaches_on_enter_and_closes_on_exit(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)

    with DuckLakeWriter() as writer:
        assert writer._con is con

    attach_call = _attach_call(con)
    queries = _queries(con)

    assert con.closed is True
    assert "INSTALL postgres" in queries
    assert "LOAD postgres" in queries
    assert "INSTALL ducklake" in queries
    assert "LOAD ducklake" in queries
    assert "ATTACH " in attach_call[0] and f'AS "{DEFAULT_DUCKLAKE_ALIAS}"' in attach_call[0]
    assert attach_call[1] is None  # all params inlined


def test_writer_uses_explicit_attach_config(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)

    with DuckLakeWriter(
        DuckLakeAttachConfig(
            attach_uri="ducklake:postgres:dbname=raw host=postgres",
            data_path="/data/custom/raw",
            metadata_schema="custom_metadata",
            alias="custom_raw",
        )
    ):
        pass

    attach_call = _attach_call(con)

    assert "ATTACH 'ducklake:postgres:dbname=raw host=postgres' AS \"custom_raw\"" in attach_call[0]
    assert "DATA_PATH '/data/custom/raw'" in attach_call[0]
    assert "METADATA_SCHEMA 'custom_metadata'" in attach_call[0]


def test_writer_appends_by_name(monkeypatch) -> None:
    con = FakeConnection()
    arrow_table = pa.table({"b": [2], "a": [1]})

    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)

    with DuckLakeWriter() as writer:
        writer.write(arrow_table, table=RawDuckLakeTable.MARKET_HISTORY)

    queries = _queries(con)

    assert con.arrow_tables == [arrow_table]
    assert len(con.relation.view_names) == 1
    assert any(
        f'INSERT INTO "{DEFAULT_DUCKLAKE_ALIAS}"."{DEFAULT_RAW_SCHEMA}"."{RawDuckLakeTable.MARKET_HISTORY.value}" BY NAME'
        in query
        for query in queries
    )
    assert any("DROP VIEW IF EXISTS" in query for query in queries)
    assert con.closed is True


def test_writer_merges_with_keys(monkeypatch) -> None:
    con = FakeConnection()
    arrow_table = pa.table({"id": [1, 2], "value": [10, 20]})

    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)

    with DuckLakeWriter() as writer:
        writer.write(
            arrow_table,
            table=RawDuckLakeTable.MARKET_ORDERS,
            key_columns=["id"],
        )

    queries = _queries(con)
    merge_queries = [query for query in queries if "MERGE INTO" in query]

    assert len(merge_queries) == 1
    assert (
        f'MERGE INTO "{DEFAULT_DUCKLAKE_ALIAS}"."{DEFAULT_RAW_SCHEMA}"."{RawDuckLakeTable.MARKET_ORDERS.value}" AS target'
        in merge_queries[0]
    )
    assert 'USING ("id")' in merge_queries[0]
    assert "WHEN NOT MATCHED THEN INSERT BY NAME" in merge_queries[0]


@pytest.mark.parametrize(
    ("key_columns", "arrow_table", "error_message"),
    [
        (
            ["item id"],
            pa.table({"item id": [1], "value": [10]}),
            "SQL identifiers must be non-empty strings without spaces or dashes",
        ),
        (
            ["id"],
            pa.table({"value": [10]}),
            "key_columns must exist in arrow_table columns",
        ),
    ],
)
def test_writer_rejects_invalid_inputs(
    monkeypatch,
    key_columns: list[str],
    arrow_table: pa.Table,
    error_message: str,
) -> None:
    con = FakeConnection()

    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)

    with DuckLakeWriter() as writer:
        with pytest.raises(ValueError, match=error_message):
            writer.write(
                arrow_table,
                table=RawDuckLakeTable.MARKET_HISTORY,
                key_columns=key_columns,
            )


def test_writer_requires_with_block() -> None:
    writer = DuckLakeWriter()

    with pytest.raises(RuntimeError, match="must be used inside a with block"):
        writer.write(
            pa.table({"id": [1]}),
            table=RawDuckLakeTable.MARKET_HISTORY,
        )


def test_writer_closes_connection_when_write_fails(monkeypatch) -> None:
    con = FakeConnection()
    con.raise_on_execute = "INSERT INTO"

    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)

    with pytest.raises(RuntimeError, match="boom"):
        with DuckLakeWriter() as writer:
            writer.write(
                pa.table({"id": [1]}),
                table=RawDuckLakeTable.MARKET_HISTORY,
            )

    assert any("DROP VIEW IF EXISTS" in query for query in _queries(con))
    assert con.closed is True


def test_writer_handles_empty_arrow_table(monkeypatch) -> None:
    con = FakeConnection()
    arrow_table = pa.table({"id": pa.array([], type=pa.int64())})

    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)

    with DuckLakeWriter() as writer:
        writer.write(arrow_table, table=RawDuckLakeTable.MARKET_HISTORY)

    assert con.arrow_tables == [arrow_table]
    assert any(
        f'INSERT INTO "{DEFAULT_DUCKLAKE_ALIAS}"."{DEFAULT_RAW_SCHEMA}"."{RawDuckLakeTable.MARKET_HISTORY.value}" BY NAME'
        in query
        for query in _queries(con)
    )


def test_writer_writes_to_multiple_tables_in_one_block(monkeypatch) -> None:
    con = FakeConnection()
    table_a = pa.table({"id": [1]})
    table_b = pa.table({"order_id": [10]})

    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)

    with DuckLakeWriter() as writer:
        writer.write(table_a, table=RawDuckLakeTable.MARKET_HISTORY)
        writer.write(table_b, table=RawDuckLakeTable.MARKET_ORDERS)

    assert con.arrow_tables == [table_a, table_b]
    queries = _queries(con)
    assert any(f'"{RawDuckLakeTable.MARKET_HISTORY.value}"' in query for query in queries)
    assert any(f'"{RawDuckLakeTable.MARKET_ORDERS.value}"' in query for query in queries)
    assert con.closed is True


def test_publish_arrow_table_one_shot(monkeypatch) -> None:
    con = FakeConnection()
    arrow_table = pa.table({"id": [1]})

    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)

    publish_arrow_table(arrow_table=arrow_table, table=RawDuckLakeTable.MARKET_HISTORY)

    assert con.closed is True
    assert any(
        f'INSERT INTO "{DEFAULT_DUCKLAKE_ALIAS}"."{DEFAULT_RAW_SCHEMA}"."{RawDuckLakeTable.MARKET_HISTORY.value}" BY NAME'
        in query
        for query in _queries(con)
    )
