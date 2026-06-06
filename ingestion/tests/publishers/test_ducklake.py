from __future__ import annotations

import logging

import pyarrow as pa
import pytest
from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig
from eve_ingest.ducklake.locks import (
    DuckLakeLockToken,
    DuckLakeLockViolationError,
    ducklake_lock_domains_for_tables,
    hold_ducklake_lock_domains,
)
from eve_ingest.ducklake.writer import DuckLakeWriter, bootstrap_raw_ducklake
from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.sources.everef.provenance import parse_last_modified_timestamp


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
        self.fetchall_result: list[tuple[object, ...]] = []
        self.fetchone_results: list[tuple[object, ...]] = []

    def execute(self, query: str, params: list[str] | None = None) -> FakeConnection:
        if self.raise_on_execute is not None and self.raise_on_execute in query:
            raise RuntimeError("boom")
        self.calls.append((query, params))
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.fetchall_result

    def fetchone(self) -> tuple[object, ...]:
        if not self.fetchone_results:
            raise AssertionError("no fetchone result queued")
        return self.fetchone_results.pop(0)

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


def _test_lock_token(
    *,
    data_tables: tuple[RawDuckLakeTable, ...] = tuple(RawDuckLakeTable),
    provenance_tables: tuple[RawDuckLakeProvenanceTable, ...] = tuple(RawDuckLakeProvenanceTable),
) -> DuckLakeLockToken:
    return DuckLakeLockToken.unsafe_for_tests(
        ducklake_lock_domains_for_tables(data_tables=data_tables, provenance_tables=provenance_tables)
    )


def test_writer_attaches_on_enter_and_closes_on_exit(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        assert writer._con is con

    attach_call = _attach_call(con)
    queries = _queries(con)

    assert con.closed is True
    assert "INSTALL postgres" in queries
    assert "LOAD postgres" in queries
    assert "INSTALL ducklake" in queries
    assert "LOAD ducklake" in queries
    assert attach_call[0].lstrip().startswith("ATTACH ")
    assert attach_call[1] is None  # all params inlined
    assert not any("CREATE SCHEMA IF NOT EXISTS" in query for query in queries)


def test_writer_uses_explicit_attach_config(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

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

    assert attach_call[0].lstrip().startswith("ATTACH ")
    assert "ducklake:postgres:dbname=raw host=postgres" in attach_call[0]
    assert "custom_raw" in attach_call[0]
    assert "/data/custom/raw" in attach_call[0]
    assert "custom_metadata" in attach_call[0]


def test_writer_replaces_table(monkeypatch) -> None:
    con = FakeConnection()
    con.fetchone_results = [(1,), (0,)]
    arrow_table = pa.table({"b": [2], "a": [1]})

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        writer.write(
            arrow_table,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
        )

    queries = _queries(con)

    assert con.arrow_tables == [arrow_table]
    assert len(con.relation.view_names) == 1
    assert "BEGIN" in queries
    assert any(query.lstrip().startswith("DELETE FROM ") for query in queries)
    assert any(query.lstrip().startswith("INSERT INTO ") and "BY NAME" in query for query in queries)
    assert "COMMIT" in queries
    assert not any(query.lstrip().startswith("CREATE OR REPLACE TABLE ") for query in queries)
    assert not any("MERGE INTO" in query for query in queries)
    assert any("DROP VIEW IF EXISTS" in query for query in queries)
    assert con.closed is True


def test_writer_merges_with_keys(monkeypatch) -> None:
    con = FakeConnection()
    con.fetchone_results = [(1,), (0,), (2,)]
    arrow_table = pa.table({"id": [1, 2], "value": [10, 20]})

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        writer.write(
            arrow_table,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["id"],
        )

    queries = _queries(con)
    merge_queries = [query for query in queries if "MERGE INTO" in query]

    assert len(merge_queries) == 1
    assert merge_queries[0].lstrip().startswith("MERGE INTO ")
    assert "USING (" in merge_queries[0]
    assert "WHEN NOT MATCHED THEN INSERT BY NAME" in merge_queries[0]


def test_writer_insert_modes_require_bootstrapped_table(monkeypatch) -> None:
    con = FakeConnection()
    con.fetchone_results = [(0,)]
    arrow_table = pa.table({"id": [1], "value": [10]})

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        with pytest.raises(RuntimeError, match="eve-ingest ducklake bootstrap raw"):
            writer.write(
                arrow_table,
                table=RawDuckLakeTable.MARKET_ORDERS,
                mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
                key_columns=["id"],
            )

    assert not any("CREATE TABLE IF NOT EXISTS" in query for query in _queries(con))


def test_writer_returns_write_metrics(monkeypatch) -> None:
    con = FakeConnection()
    con.fetchone_results = [(1,), (1,), (1,)]
    arrow_table = pa.table({"id": [1, 2], "value": [10, 20]})

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        metrics = writer.write(
            arrow_table,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["id"],
        )

    assert metrics.attempted_rows == 2
    assert metrics.inserted_rows == 1
    assert metrics.matched_rows == 1
    assert metrics.replaced_rows == 0


def test_replace_table_returns_replaced_row_metrics(monkeypatch) -> None:
    con = FakeConnection()
    con.fetchone_results = [(1,), (7,)]
    arrow_table = pa.table({"id": [1]})

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        metrics = writer.write(
            arrow_table,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
        )

    assert metrics.attempted_rows == 1
    assert metrics.inserted_rows == 1
    assert metrics.matched_rows == 0
    assert metrics.replaced_rows == 7


@pytest.mark.parametrize(
    ("key_columns", "arrow_table", "error_message"),
    [
        (
            [],
            pa.table({"id": [1], "value": [10]}),
            "key_columns must not be empty when writer mode requires keys",
        ),
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

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        with pytest.raises(ValueError, match=error_message):
            writer.write(
                arrow_table,
                table=RawDuckLakeTable.MARKET_HISTORY,
                mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
                key_columns=key_columns,
            )


def test_writer_requires_lock_token_for_write(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter() as writer:
        with pytest.raises(DuckLakeLockViolationError, match="requires DuckLakeLockToken"):
            writer.write(
                pa.table({"id": [1]}),
                table=RawDuckLakeTable.MARKET_HISTORY,
                mode=DuckLakeWriterMode.REPLACE_TABLE,
            )

    assert con.arrow_tables == []


def test_writer_rejects_declared_mode_mismatch_before_arrow_view_or_mutation(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(
        lock_token=_test_lock_token(),
        declared_mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
        dataset_name="market-orders",
    ) as writer:
        with pytest.raises(
            ValueError,
            match=(
                "DuckLake writer mode does not match publisher declaration "
                "dataset=market-orders table=raw_market_orders "
                "declared_mode=insert_missing_keys requested_mode=replace_table"
            ),
        ):
            writer.write(
                pa.table({"id": [1]}),
                table=RawDuckLakeTable.MARKET_ORDERS,
                mode=DuckLakeWriterMode.REPLACE_TABLE,
            )

    assert con.arrow_tables == []
    assert not any(query.lstrip().startswith(("DELETE FROM", "INSERT INTO", "MERGE INTO")) for query in _queries(con))


def test_writer_rejects_wrong_lock_token_for_write(monkeypatch) -> None:
    con = FakeConnection()
    token = _test_lock_token(
        data_tables=(RawDuckLakeTable.MARKET_HISTORY,),
        provenance_tables=(),
    )

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=token) as writer:
        with pytest.raises(DuckLakeLockViolationError, match="raw_market_orders"):
            writer.write(
                pa.table({"id": [1]}),
                table=RawDuckLakeTable.MARKET_ORDERS,
                mode=DuckLakeWriterMode.REPLACE_TABLE,
            )

    assert con.arrow_tables == []


def test_writer_rejects_reused_inactive_lock_token_before_mutation(monkeypatch) -> None:
    con = FakeConnection()
    with hold_ducklake_lock_domains(
        catalog_url="postgresql://user:pass@localhost:5432/db",
        lock_domains=(),
        timeout_seconds=0.1,
    ) as token:
        assert token.is_active is True

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=token) as writer:
        with pytest.raises(DuckLakeLockViolationError, match="inactive"):
            writer.write(
                pa.table({"id": [1]}),
                table=RawDuckLakeTable.MARKET_HISTORY,
                mode=DuckLakeWriterMode.REPLACE_TABLE,
            )

    assert con.arrow_tables == []
    assert not any(query.lstrip().startswith(("DELETE FROM", "INSERT INTO", "MERGE INTO")) for query in _queries(con))


def test_writer_requires_lock_token_for_source_object(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter() as writer:
        with pytest.raises(DuckLakeLockViolationError, match="requires DuckLakeLockToken"):
            writer.upsert_source_object(
                {"source_object_id": "soid-1", "status": "failed"},
                table=RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,
            )

    assert not any(query.lstrip().startswith("MERGE INTO") for query in _queries(con))


def test_writer_rejects_wrong_lock_token_for_source_object(monkeypatch) -> None:
    con = FakeConnection()
    token = _test_lock_token(
        data_tables=(),
        provenance_tables=(RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS,),
    )

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=token) as writer:
        with pytest.raises(DuckLakeLockViolationError, match="raw_market_orders_objects"):
            writer.upsert_source_object(
                {"source_object_id": "soid-1", "status": "failed"},
                table=RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,
            )

    assert not any(query.lstrip().startswith("MERGE INTO") for query in _queries(con))


def test_writer_requires_with_block() -> None:
    writer = DuckLakeWriter()

    with pytest.raises(RuntimeError, match="must be used inside a with block"):
        writer.write(
            pa.table({"id": [1]}),
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
        )


def test_writer_closes_connection_when_write_fails(monkeypatch) -> None:
    con = FakeConnection()
    con.fetchone_results = [(1,), (0,)]
    con.raise_on_execute = "INSERT INTO"

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with pytest.raises(RuntimeError, match="boom"):
        with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
            writer.write(
                pa.table({"id": [1]}),
                table=RawDuckLakeTable.MARKET_HISTORY,
                mode=DuckLakeWriterMode.REPLACE_TABLE,
            )

    assert any("DROP VIEW IF EXISTS" in query for query in _queries(con))
    assert "ROLLBACK" in _queries(con)
    assert con.closed is True


def test_replace_table_rejects_empty_arrow_table_without_writing(monkeypatch) -> None:
    con = FakeConnection()
    arrow_table = pa.table({"id": pa.array([], type=pa.int64())})

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        with pytest.raises(ValueError, match="REPLACE_TABLE requires a non-empty arrow_table"):
            writer.write(
                arrow_table,
                table=RawDuckLakeTable.MARKET_HISTORY,
                mode=DuckLakeWriterMode.REPLACE_TABLE,
            )

    assert con.arrow_tables == []
    assert not any(query.lstrip().startswith("CREATE OR REPLACE TABLE ") for query in _queries(con))


def test_replace_table_rejects_key_columns(monkeypatch) -> None:
    con = FakeConnection()
    arrow_table = pa.table({"id": [1]})

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        with pytest.raises(ValueError, match="REPLACE_TABLE does not accept key_columns"):
            writer.write(
                arrow_table,
                table=RawDuckLakeTable.MARKET_HISTORY,
                mode=DuckLakeWriterMode.REPLACE_TABLE,
                key_columns=["id"],
            )

    assert not any(query.lstrip().startswith("CREATE OR REPLACE TABLE ") for query in _queries(con))


def test_nested_transactions_only_begin_and_commit_once(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        with writer.transaction():
            with writer.transaction():
                writer.upsert_source_object(
                    {
                        "source_object_id": "soid-1",
                        "status": "parsed",
                    },
                    table=RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS,
                )

    queries = _queries(con)
    assert queries.count("BEGIN") == 1
    assert queries.count("COMMIT") == 1
    assert "ROLLBACK" not in queries


def test_writer_writes_to_multiple_tables_in_one_block(monkeypatch) -> None:
    con = FakeConnection()
    con.fetchone_results = [(0,), (0,), (1,)]
    table_a = pa.table({"id": [1]})
    table_b = pa.table({"order_id": [10]})

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)
    monkeypatch.setattr("eve_ingest.ducklake.writer._target_exists", lambda *args, **kwargs: True)

    bootstrap_raw_ducklake()

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        writer.write(table_a, table=RawDuckLakeTable.MARKET_HISTORY, mode=DuckLakeWriterMode.REPLACE_TABLE)
        writer.write(
            table_b,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=["order_id"],
        )

    assert con.arrow_tables == [table_a, table_b]
    queries = _queries(con)
    assert any(f'"{RawDuckLakeTable.MARKET_HISTORY.value}"' in query for query in queries)
    assert any(f'"{RawDuckLakeTable.MARKET_ORDERS.value}"' in query for query in queries)
    assert con.closed is True


def test_upsert_source_object_uses_merge(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        writer.upsert_source_object(
            {
                "source_object_id": "soid-1",
                "source_system": "everef",
                "endpoint": "market_orders",
                "source_url": "https://example.com/file.csv.bz2",
                "status": "failed",
                "status_reason": "boom",
            },
            table=RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,
        )
        writer.upsert_source_object(
            {
                "source_object_id": "soid-1",
                "status": "ingested",
                "status_reason": None,
            },
            table=RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,
        )

    merge_queries = [call for call in con.calls if call[0].lstrip().startswith("MERGE INTO")]
    assert len(merge_queries) == 2
    assert "source.source_object_id" in merge_queries[0][0]
    assert merge_queries[1][1] == ["soid-1", "ingested", None]


def test_bootstrap_raw_ducklake_creates_all_raw_and_provenance_tables(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    bootstrap_raw_ducklake()

    queries = _queries(con)
    assert any("CREATE SCHEMA IF NOT EXISTS" in query for query in queries)
    for table in RawDuckLakeTable:
        assert any(f'"{table.value}"' in query for query in queries)
    for table in RawDuckLakeProvenanceTable:
        assert any(f'"{table.value}"' in query for query in queries)


def test_parse_last_modified_timestamp_supports_iso_and_http_date() -> None:
    iso_value = parse_last_modified_timestamp("2026-01-02T11:01:55Z")
    http_value = parse_last_modified_timestamp("Fri, 02 Jan 2026 11:01:55 GMT")

    assert iso_value == http_value


def test_parse_last_modified_timestamp_returns_none_for_invalid_value(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("eve_ingest.sources.everef")
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=logger.name):
            value = parse_last_modified_timestamp("not-a-timestamp")
            assert value is None
            assert "Could not parse last_modified timestamp" in caplog.text
    finally:
        logger.removeHandler(caplog.handler)
