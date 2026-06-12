from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pyarrow as pa
import pytest
from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig, build_ducklake_attach_config_from_url
from eve_ingest.ducklake.bootstrap import bootstrap_raw_ducklake
from eve_ingest.ducklake.locks import (
    DuckLakeLockTimeoutError,
    DuckLakeLockToken,
    ducklake_lock_domains_for_tables,
    hold_ducklake_lock_domains,
)
from eve_ingest.ducklake.provenance import SourceObjectProvenanceRepository
from eve_ingest.ducklake.raw_publish import RawTablePublisher
from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriterMode,
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
)
from eve_ingest.ducklake.session import DuckLakeSession, SqlSource
from eve_ingest.ducklake.sql import quote_identifier
from eve_ingest.publication.prepared_source import PreparedSnapshotSqlSource
from eve_ingest.publication.service import PublicationService
from eve_ingest.publication.source_prep import SourcePreparationContext
from eve_ingest.publication.specs import (
    AppendSnapshotRows,
    DatasetPublisherSpec,
    SourceDateScope,
)
from eve_ingest.raw_objects import UpdateMode
from tests.sources.everef.conftest import make_cache_result

if TYPE_CHECKING:
    from pathlib import Path

    import duckdb


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


def _test_lock_token() -> DuckLakeLockToken:
    return DuckLakeLockToken.unsafe_for_tests(
        ducklake_lock_domains_for_tables(
            data_tables=tuple(RawDuckLakeTable),
            provenance_tables=tuple(RawDuckLakeProvenanceTable),
        )
    )


@pytest.mark.integration
def test_real_ducklake_session_with_pg_attach(
    attach_config: DuckLakeAttachConfig, raw_con: duckdb.DuckDBPyConnection
) -> None:
    bootstrap_raw_ducklake(attach_config)

    market_orders_data = pa.table(
        {
            "order_id": [101],
            "price": [15.0],
            "source_ref_id": ["soid-pg-1"],
            "source_market_date": [date(2026, 1, 1)],
            "snapshot_ts": [datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)],
        }
    )
    market_history_data = pa.table(
        {
            "type_id": [42],
            "average": [5.0],
            "date": [date(2026, 1, 1)],
            "source_market_date": [date(2026, 1, 1)],
        }
    )

    with DuckLakeSession(attach_config, lock_token=_test_lock_token()) as session:
        raw = RawTablePublisher(session, lock_token=_test_lock_token())
        raw.write(
            market_orders_data,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        )
        raw.write(
            market_history_data,
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
        )

    alias = quote_identifier(attach_config.alias)
    order_rows = raw_con.execute(
        f"SELECT order_id, price FROM {alias}.raw.raw_market_orders WHERE order_id = 101"
    ).fetchall()
    assert order_rows == [(101, 15.0)]

    history_rows = raw_con.execute(
        f"SELECT type_id, average FROM {alias}.raw.raw_market_history WHERE type_id = 42"
    ).fetchall()
    assert history_rows == [(42, 5.0)]


@pytest.mark.integration
def test_real_lock_domains_with_pg(pg_url: str) -> None:
    lock_domain = "ducklake:raw:raw_market_history"

    with hold_ducklake_lock_domains(
        catalog_url=pg_url,
        lock_domains=(lock_domain,),
        timeout_seconds=5,
    ) as first_token:
        assert first_token.is_active is True
        first_token.require_domain(lock_domain)

        with (
            pytest.raises(DuckLakeLockTimeoutError, match=lock_domain),
            hold_ducklake_lock_domains(
                catalog_url=pg_url,
                lock_domains=(lock_domain,),
                timeout_seconds=0.1,
            ),
        ):
            pytest.fail("concurrent lock acquisition should have timed out")

    with hold_ducklake_lock_domains(
        catalog_url=pg_url,
        lock_domains=(lock_domain,),
        timeout_seconds=5,
    ) as second_token:
        assert second_token.is_active is True

    assert first_token.is_active is False


@pytest.mark.integration
def test_bootstrap_with_real_pg_is_idempotent(
    attach_config: DuckLakeAttachConfig,
) -> None:
    bootstrap_raw_ducklake(attach_config)
    bootstrap_raw_ducklake(attach_config)

    session = DuckLakeSession(attach_config)
    session.__enter__()
    con = session.connection
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'raw'"
            ).fetchall()
        }
        for table in RawDuckLakeTable:
            assert table.value in tables
        for table in RawDuckLakeProvenanceTable:
            assert table.value in tables
    finally:
        con.close()


@pytest.mark.integration
def test_prepare_arrow_source(attach_config: DuckLakeAttachConfig) -> None:
    bootstrap_raw_ducklake(attach_config)
    with DuckLakeSession(attach_config, lock_token=_test_lock_token()) as session:
        prep_ctx = SourcePreparationContext(session=session)
        arrow_table = pa.table({"x": [1, 2], "y": [10, 20]})
        with prep_ctx.prepare_arrow_source(arrow_table) as source_name:
            rows = session.connection.execute(f"SELECT * FROM {quote_identifier(source_name)} ORDER BY x").fetchall()
            assert rows == [(1, 10), (2, 20)]


@pytest.mark.integration
def test_prepare_sql_source(attach_config: DuckLakeAttachConfig) -> None:
    bootstrap_raw_ducklake(attach_config)
    with DuckLakeSession(attach_config, lock_token=_test_lock_token()) as session:
        prep_ctx = SourcePreparationContext(session=session)
        sql_source = SqlSource(sql="SELECT 42 AS val, 'hello' AS msg")
        with prep_ctx.prepare_sql_source(sql_source) as source_name:
            rows = session.connection.execute(f"SELECT * FROM {quote_identifier(source_name)}").fetchall()
            assert rows == [(42, "hello")]


@pytest.mark.integration
def test_publish_context_with_real_components(
    attach_config: DuckLakeAttachConfig,
    raw_con: duckdb.DuckDBPyConnection,
) -> None:
    bootstrap_raw_ducklake(attach_config)

    spec = DatasetPublisherSpec(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        data_tables=(RawDuckLakeTable.MARKET_ORDERS,),
        provenance_tables=(RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,),
        publication_scope=SourceDateScope("market_orders"),
        write_policy=AppendSnapshotRows(),
    )
    raw_object = make_cache_result(
        "/tmp/test_pg_ctx.csv",
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://example.com/market-orders/pg_ctx.csv.bz2",
        identity_hash="hash-pg-ctx",
    )
    sql_source = SqlSource(
        sql="""SELECT 1 AS order_id, 34 AS type_id, 10000001 AS region_id, 9.99 AS price,
                      'soid-pg-ctx' AS source_ref_id,
                      DATE '2026-01-01' AS source_market_date,
                      TIMESTAMP '2026-01-01 00:00:00' AS snapshot_ts"""
    )
    prepared = PreparedSnapshotSqlSource(
        raw_object=raw_object,
        source_system="everef",
        endpoint="market_orders",
        source_market_date=date(2026, 1, 1),
        snapshot_ts=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        table=RawDuckLakeTable.MARKET_ORDERS,
        sql_source=sql_source,
    )

    lock_token = _test_lock_token()
    with DuckLakeSession(attach_config, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        result = service.append_snapshot(prepared, ctx=prep_ctx, source_ref_id="soid-pg-ctx")

    assert result.success is True
    assert result.source_date == "2026-01-01"
    assert len(result.write_metrics) == 1
    assert result.write_metrics[0].inserted_rows == 1

    alias = quote_identifier(attach_config.alias)
    rows = raw_con.execute(f"SELECT order_id, price, source_ref_id FROM {alias}.raw.raw_market_orders").fetchall()
    assert rows == [(1, 9.99, "soid-pg-ctx")]

    prov_rows = raw_con.execute(f"SELECT source_ref_id, status FROM {alias}.raw.raw_market_orders_objects").fetchall()
    assert prov_rows == [("soid-pg-ctx", "ingested")]
