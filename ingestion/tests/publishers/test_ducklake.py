from __future__ import annotations

import pytest
import pyarrow as pa

from ingest.publishers.ducklake import (
    DEFAULT_DUCKLAKE_ALIAS,
    DuckLakeWriter,
    DuckLakeAttachConfig,
    RawDuckLakeTable,
    _attach_ducklake,
    _build_default_attach_config,
)
from ingest.util import (
    DEFAULT_DUCKLAKE_CATALOG,
    DEFAULT_DUCKLAKE_METADATA_SCHEMA,
    DEFAULT_DUCKLAKE_RAW_DATA_PATH,
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


def test_build_default_attach_config_uses_shared_raw_ducklake_defaults() -> None:
    assert _build_default_attach_config() == DuckLakeAttachConfig(
        attach_uri=(
            "ducklake:postgres:dbname=airflow host=postgres port=5432 "
            "user=airflow password=airflow-local-only"
        ),
        data_path=DEFAULT_DUCKLAKE_RAW_DATA_PATH,
        metadata_schema=DEFAULT_DUCKLAKE_METADATA_SCHEMA,
        alias=DEFAULT_DUCKLAKE_ALIAS,
    )


def test_attach_ducklake_executes_expected_statements() -> None:
    con = FakeConnection()

    _attach_ducklake(
        con,
        config=DuckLakeAttachConfig(
            attach_uri="ducklake:postgres:dbname=airflow host=127.0.0.1",
            data_path="/opt/eve-market/data/datasets/ducklake/raw",
            metadata_schema="eve_market",
            alias="raw_lake",
        ),
    )

    attach_call = con.calls[-1]
    queries = _queries(con)

    assert "INSTALL postgres" in queries
    assert "LOAD postgres" in queries
    assert "INSTALL ducklake" in queries
    assert "LOAD ducklake" in queries
    assert 'ATTACH ? AS "raw_lake"' in attach_call[0]
    assert attach_call[1] == [
        "ducklake:postgres:dbname=airflow host=127.0.0.1",
        "/opt/eve-market/data/datasets/ducklake/raw",
        "eve_market",
    ]


def test_writer_attaches_on_enter_and_closes_on_exit(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)

    with DuckLakeWriter() as writer:
        assert writer._con is con

    attach_call = con.calls[-1]
    queries = _queries(con)

    assert con.closed is True
    assert "INSTALL postgres" in queries
    assert "LOAD postgres" in queries
    assert "INSTALL ducklake" in queries
    assert "LOAD ducklake" in queries
    assert 'ATTACH ? AS "ducklake"' in attach_call[0]
    assert attach_call[1] == [
        "ducklake:postgres:dbname=airflow host=postgres port=5432 user=airflow password=airflow-local-only",
        DEFAULT_DUCKLAKE_RAW_DATA_PATH,
        DEFAULT_DUCKLAKE_METADATA_SCHEMA,
    ]


def test_writer_accepts_explicit_attach_config(monkeypatch) -> None:
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

    attach_call = con.calls[-1]

    assert 'ATTACH ? AS "custom_raw"' in attach_call[0]
    assert attach_call[1] == [
        "ducklake:postgres:dbname=raw host=postgres",
        "/data/custom/raw",
        "custom_metadata",
    ]


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
        'INSERT INTO "ducklake"."raw"."raw_market_history" BY NAME' in query
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
            merge_keys=["id"],
        )

    queries = _queries(con)
    merge_queries = [query for query in queries if "MERGE INTO" in query]

    assert len(merge_queries) == 1
    assert (
        'MERGE INTO "ducklake"."raw"."raw_market_orders" AS target' in merge_queries[0]
    )
    assert 'USING ("id")' in merge_queries[0]
    assert "WHEN NOT MATCHED THEN INSERT BY NAME" in merge_queries[0]


@pytest.mark.parametrize(
    ("merge_keys", "arrow_table", "error_message"),
    [
        (
            ["item id"],
            pa.table({"item id": [1], "value": [10]}),
            "SQL identifiers must be non-empty strings without spaces or dashes",
        ),
        (
            ["id"],
            pa.table({"value": [10]}),
            "merge_keys must exist in arrow_table columns",
        ),
    ],
)
def test_writer_rejects_invalid_inputs(
    monkeypatch,
    merge_keys: list[str],
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
                merge_keys=merge_keys,
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

    assert con.closed is True
