from __future__ import annotations

import pyarrow as pa
import pytest
from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig
from eve_ingest.ducklake.locks import (
    DuckLakeLockToken,
    DuckLakeLockViolationError,
    ducklake_lock_domains_for_tables,
    hold_ducklake_lock_domains,
)
from eve_ingest.ducklake.writer import DuckLakeWriter, _ensure_expected_partitioning, bootstrap_raw_ducklake
from eve_ingest.ducklake.raw_tables import (
    DuckLakeTableTarget,
    DuckLakeWriterMode,
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
)


class FakeRelation:
    def __init__(self) -> None:
        self.view_names: list[str] = []

    def create_view(self, view_name: str) -> None:
        self.view_names.append(view_name)


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str] | None]] = []
        self.events: list[tuple[str, str | None]] = []
        self.relation = FakeRelation()
        self.arrow_tables: list[pa.Table] = []
        self.closed = False
        self.raise_on_execute: str | None = None
        self.fetchall_result: list[tuple[object, ...]] = []
        self._next_fetchall_result: list[tuple[object, ...]] | None = None
        self.source_object_update_rows: list[tuple[object, ...]] = [("soid-1",)]
        self.fetchone_results: list[tuple[object, ...]] = []

    def execute(self, query: str, params: list[str] | None = None) -> FakeConnection:
        if self.raise_on_execute is not None and self.raise_on_execute in query:
            raise RuntimeError("boom")
        self.calls.append((query, params))
        self.events.append(("execute", query))
        if "RETURNING source_object_id" in query:
            self._next_fetchall_result = self.source_object_update_rows
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        if self._next_fetchall_result is not None:
            result = self._next_fetchall_result
            self._next_fetchall_result = None
            return result
        return self.fetchall_result

    def fetchone(self) -> tuple[object, ...]:
        if not self.fetchone_results:
            raise AssertionError("no fetchone result queued")
        return self.fetchone_results.pop(0)

    def from_arrow(self, arrow_table: pa.Table) -> FakeRelation:
        self.arrow_tables.append(arrow_table)
        self.events.append(("from_arrow", None))
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


def test_writer_configures_postgres_pool_before_ducklake_attach(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(
        DuckLakeAttachConfig(
            attach_uri="ducklake:postgres:dbname=raw host=postgres",
            data_path="/data/custom/raw",
            postgres_pool_max_connections=32,
            postgres_pool_wait_timeout_millis=120000,
            postgres_pool_acquire_mode="wait",
        )
    ):
        pass

    queries = _queries(con)
    attach_index = next(index for index, query in enumerate(queries) if "ATTACH " in query)

    assert queries.index("SET pg_pool_max_connections = 32") < attach_index
    assert queries.index("SET pg_pool_wait_timeout_millis = 120000") < attach_index
    assert queries.index("SET pg_pool_acquire_mode = 'wait'") < attach_index


def test_bootstrap_repairs_missing_columns(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    bootstrap_raw_ducklake()

    queries = _queries(con)

    assert any(
        query.lstrip().startswith("ALTER TABLE ")
        and RawDuckLakeTable.MARKET_ORDERS.value in query
        and "ADD COLUMN IF NOT EXISTS station_id BIGINT" in query
        for query in queries
    )
    assert any(
        query.lstrip().startswith("ALTER TABLE ")
        and RawDuckLakeTable.MARKET_ORDERS.value in query
        and "ADD COLUMN IF NOT EXISTS constellation_id BIGINT" in query
        for query in queries
    )
    assert con.closed is True


def test_bootstrap_partitions_snapshot_order_tables(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    bootstrap_raw_ducklake()

    queries = _queries(con)

    assert any(
        query.lstrip().startswith("ALTER TABLE ")
        and RawDuckLakeTable.MARKET_ORDERS.value in query
        and "SET PARTITIONED BY" in query
        and '"source_market_date"' in query
        for query in queries
    )
    assert any(
        query.lstrip().startswith("ALTER TABLE ")
        and RawDuckLakeTable.FUZZWORK_ORDERS.value in query
        and "SET PARTITIONED BY" in query
        and '"source_market_date"' in query
        for query in queries
    )


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


def test_writer_authoritative_mode_merges_with_keys(monkeypatch) -> None:
    con = FakeConnection()
    con.fetchone_results = [(1,), (0,), (2,)]
    arrow_table = pa.table({"id": [1, 2], "value": [10, 20]})

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        writer.write(
            arrow_table,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["id"],
        )

    queries = _queries(con)
    merge_queries = [query for query in queries if "MERGE INTO" in query]

    assert len(merge_queries) == 1
    assert merge_queries[0].lstrip().startswith("MERGE INTO ")
    assert "USING (" in merge_queries[0]
    assert "WHEN NOT MATCHED THEN INSERT BY NAME" in merge_queries[0]


def test_writer_append_snapshot_rows_inserts_by_name_without_merge_or_counts(monkeypatch) -> None:
    con = FakeConnection()
    con.fetchone_results = [(1,)]
    arrow_table = pa.table(
        {
            "price": [10.0, 20.0],
            "order_id": [1, 2],
            "source_object_id": ["soid-1", "soid-1"],
            "source_market_date": ["2026-01-01", "2026-01-01"],
            "snapshot_ts": ["2026-01-01", "2026-01-01"],
        }
    )

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        metrics = writer.write(
            arrow_table,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        )

    queries = _queries(con)
    insert_queries = [query for query in queries if query.lstrip().startswith("INSERT INTO")]

    assert len(insert_queries) == 1
    assert "BY NAME" in insert_queries[0]
    assert "SELECT * FROM" in insert_queries[0]
    assert not any("MERGE INTO" in query for query in queries)
    assert not any("WHERE EXISTS" in query or "WHERE NOT EXISTS" in query for query in queries)
    assert metrics.attempted_rows == 2
    assert metrics.inserted_rows == 2
    assert metrics.matched_rows == 0
    assert metrics.replaced_rows == 0


@pytest.mark.parametrize(
    "mode",
    [
        DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
        DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
    ],
)
def test_writer_insert_modes_require_bootstrapped_table(monkeypatch, mode: DuckLakeWriterMode) -> None:
    con = FakeConnection()
    con.fetchone_results = [(0,)]
    arrow_table = pa.table(
        {
            "id": [1],
            "source_object_id": ["soid-1"],
            "source_market_date": ["2026-01-01"],
            "snapshot_ts": ["2026-01-01"],
            "value": [10],
        }
    )

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        with pytest.raises(RuntimeError, match="eve-ingest ducklake bootstrap raw"):
            writer.write(
                arrow_table,
                table=RawDuckLakeTable.MARKET_ORDERS
                if mode is DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS
                else RawDuckLakeTable.MARKET_HISTORY,
                mode=mode,
                key_columns=[] if mode is DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS else ["id"],
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
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
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
def test_writer_rejects_invalid_key_columns(
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
                mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
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
        declared_mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
        dataset_name="market-orders",
    ) as writer:
        with pytest.raises(
            ValueError,
            match=(
                "DuckLake writer mode does not match publisher declaration "
                "dataset=market-orders table=raw_market_orders "
                "declared_mode=assert_partition_coverage_insert_missing_keys requested_mode=replace_table"
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
        with pytest.raises(DuckLakeLockViolationError, match="require DuckLakeLockToken"):
            writer.record_source_object(
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
            writer.record_source_object(
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


def test_append_snapshot_rows_rejects_key_columns(monkeypatch) -> None:
    con = FakeConnection()
    arrow_table = pa.table({"id": [1]})

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        with pytest.raises(ValueError, match="APPEND_SNAPSHOT_ROWS does not accept key_columns"):
            writer.write(
                arrow_table,
                table=RawDuckLakeTable.MARKET_ORDERS,
                mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
                key_columns=["id"],
            )

    assert con.arrow_tables == []


def test_append_snapshot_rows_requires_provenance_and_snapshot_columns(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        with pytest.raises(
            ValueError,
            match="APPEND_SNAPSHOT_ROWS requires arrow_table columns: source_object_id, source_market_date, snapshot_ts",
        ):
            writer.write(
                pa.table({"order_id": [1]}),
                table=RawDuckLakeTable.MARKET_ORDERS,
                mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
            )

    assert con.arrow_tables == []


def test_nested_transactions_only_begin_and_commit_once(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        with writer.transaction():
            with writer.transaction():
                writer.mark_source_object_parsed("soid-1", table=RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS)

    queries = _queries(con)
    assert queries.count("BEGIN") == 1
    assert queries.count("COMMIT") == 1
    assert "ROLLBACK" not in queries


def test_nested_transaction_inner_failure_marks_outer_rollback_only(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        with pytest.raises(RuntimeError, match="rollback-only"):
            with writer.transaction():
                try:
                    with writer.transaction():
                        raise ValueError("inner")
                except ValueError:
                    pass

    queries = _queries(con)
    assert queries.count("BEGIN") == 1
    assert "ROLLBACK" in queries
    assert "COMMIT" not in queries


def test_transaction_rolls_back_when_commit_fails(monkeypatch) -> None:
    con = FakeConnection()
    con.raise_on_execute = "COMMIT"

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        with pytest.raises(RuntimeError, match="boom"):
            with writer.transaction():
                pass
        assert writer._transaction_depth == 0

    queries = _queries(con)
    assert "BEGIN" in queries
    assert "ROLLBACK" in queries


def test_prepared_source_write_does_not_create_arrow_view_inside_outer_transaction(monkeypatch) -> None:
    con = FakeConnection()
    con.fetchone_results = [(1,), (0,), (1,)]
    arrow_table = pa.table({"type_id": [10], "price": [99.5], "source_market_date": ["2026-01-01"]})

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        writer.validate_write_request(
            arrow_table,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=["type_id"],
        )
        with writer.prepare_arrow_source(arrow_table) as source_name:
            with writer.transaction():
                writer.mark_source_object_parsed("soid-1", table=RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS)
                writer.write_prepared_source(
                    arrow_table,
                    source_name=source_name,
                    table=RawDuckLakeTable.MARKET_HISTORY,
                    mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
                    key_columns=["type_id"],
                )

    event_names = [event[0] for event in con.events]
    begin_index = next(i for i, event in enumerate(con.events) if event == ("execute", "BEGIN"))
    raw_merge_index = next(
        i
        for i, event in enumerate(con.events)
        if event[0] == "execute" and "MERGE INTO" in event[1] and RawDuckLakeTable.MARKET_HISTORY.value in event[1]
    )

    assert event_names.count("from_arrow") == 1
    assert event_names.index("from_arrow") < begin_index
    assert not any(event[0] == "from_arrow" for event in con.events[begin_index:raw_merge_index])


def test_writer_records_multiple_table_writes_in_one_block(monkeypatch) -> None:
    con = FakeConnection()
    con.fetchone_results = [(0,), (0,), (1,)]
    table_a = pa.table({"id": [1]})
    table_b = pa.table(
        {
            "order_id": [10],
            "source_object_id": ["soid-1"],
            "source_market_date": ["2026-01-01"],
            "snapshot_ts": ["2026-01-01"],
        }
    )

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)
    monkeypatch.setattr("eve_ingest.ducklake.writer._target_exists", lambda *args, **kwargs: True)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        metrics_a = writer.write(table_a, table=RawDuckLakeTable.MARKET_HISTORY, mode=DuckLakeWriterMode.REPLACE_TABLE)
        metrics_b = writer.write(
            table_b,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        )
        assert writer.write_history == (metrics_a, metrics_b)

    assert con.arrow_tables == [table_a, table_b]
    queries = _queries(con)
    assert any(f'"{RawDuckLakeTable.MARKET_HISTORY.value}"' in query for query in queries)
    assert any(f'"{RawDuckLakeTable.MARKET_ORDERS.value}"' in query for query in queries)
    assert not any(query.lstrip().startswith("CREATE TABLE IF NOT EXISTS") for query in queries)
    assert metrics_a.replaced_rows == 0
    assert metrics_b.matched_rows == 0
    assert metrics_b.inserted_rows == 1
    assert con.closed is True


def test_record_source_object_uses_merge_and_status_methods_update(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        writer.record_source_object(
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
        writer.mark_source_object_ingested(
            "soid-1", row_count=7, table=RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS
        )

    merge_queries = [call for call in con.calls if call[0].lstrip().startswith("MERGE INTO")]
    update_queries = [call for call in con.calls if call[0].lstrip().startswith("UPDATE")]
    assert len(merge_queries) == 1
    assert len(update_queries) == 1
    assert "source.source_object_id" in merge_queries[0][0]
    assert update_queries[0][1][-1] == "soid-1"


def test_mark_source_object_status_raises_when_row_missing(monkeypatch) -> None:
    con = FakeConnection()
    con.source_object_update_rows = []

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        with pytest.raises(RuntimeError, match="Missing source object provenance row"):
            writer.mark_source_object_failed(
                "missing-soid",
                reason="boom",
                table=RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,
            )


def test_ensure_expected_partitioning_skips_alter_when_metadata_matches(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr(
        "eve_ingest.ducklake.writer._ducklake_partition_columns", lambda *args, **kwargs: ("source_market_date",)
    )

    _ensure_expected_partitioning(
        con,
        alias="raw_lake",
        target=DuckLakeTableTarget(schema="raw", table="raw_market_orders"),
        partition_columns=("source_market_date",),
    )

    assert not any("SET PARTITIONED BY" in query for query in _queries(con))


def test_ensure_expected_partitioning_emits_exact_target_when_missing(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr("eve_ingest.ducklake.writer._ducklake_partition_columns", lambda *args, **kwargs: ())

    _ensure_expected_partitioning(
        con,
        alias="raw_lake",
        target=DuckLakeTableTarget(schema="raw", table="raw_market_orders"),
        partition_columns=("source_market_date",),
    )

    partition_queries = [query for query in _queries(con) if "SET PARTITIONED BY" in query]
    assert len(partition_queries) == 1
    assert 'ALTER TABLE "raw_lake"."raw"."raw_market_orders"' in partition_queries[0]
    assert 'SET PARTITIONED BY ("source_market_date")' in partition_queries[0]


def test_ensure_expected_partitioning_raises_when_metadata_differs(monkeypatch) -> None:
    con = FakeConnection()

    monkeypatch.setattr(
        "eve_ingest.ducklake.writer._ducklake_partition_columns", lambda *args, **kwargs: ("region_id",)
    )

    with pytest.raises(RuntimeError, match="partitioning differs"):
        _ensure_expected_partitioning(
            con,
            alias="raw_lake",
            target=DuckLakeTableTarget(schema="raw", table="raw_market_orders"),
            partition_columns=("source_market_date",),
        )


@pytest.mark.parametrize(("fetchone_result", "expected"), [((1,), True), (None, False)])
def test_source_object_version_is_ingested_queries_status_and_sha(monkeypatch, fetchone_result, expected) -> None:
    con = FakeConnection()
    con.fetchone_results = [fetchone_result]

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        assert (
            writer.source_object_version_is_ingested(
                "soid-1", sha256="abc123", table=RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS
            )
            is expected
        )

    calls = con.calls
    assert calls[-1][1] == ["soid-1", "abc123"]
    assert "status = 'ingested'" in calls[-1][0]
    assert "sha256 = ?" in calls[-1][0]


@pytest.mark.parametrize(("fetchone_result", "expected"), [(("abc123",), "abc123"), (None, None)])
def test_source_object_ingested_sha256_queries_status(monkeypatch, fetchone_result, expected) -> None:
    con = FakeConnection()
    con.fetchone_results = [fetchone_result]

    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)

    with DuckLakeWriter(lock_token=_test_lock_token()) as writer:
        assert (
            writer.source_object_ingested_sha256("soid-1", table=RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS)
            == expected
        )

    calls = con.calls
    assert calls[-1][1] == ["soid-1"]
    assert "SELECT sha256" in calls[-1][0]
    assert "status = 'ingested'" in calls[-1][0]


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
