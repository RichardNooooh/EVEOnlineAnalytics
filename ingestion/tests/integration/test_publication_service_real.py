from __future__ import annotations

from datetime import UTC, date, datetime

import pyarrow as pa
import pytest
from eve_ingest.ducklake.provenance import SourceObjectProvenanceRepository
from eve_ingest.ducklake.raw_publish import RawTablePublisher
from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriteMetrics,
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
)
from eve_ingest.ducklake.session import DuckLakeSession, SqlSource
from eve_ingest.publication.prepared_source import (
    PreparedAuthoritativeArrowSource,
    PreparedReferenceTableSource,
    PreparedSnapshotSqlSource,
)
from eve_ingest.publication.service import PublicationService
from eve_ingest.publication.source_prep import SourcePreparationContext
from eve_ingest.publication.specs import (
    AppendSnapshotRows,
    DatasetPublisherSpec,
    InsertMissingKeysAuthoritativePartition,
    ReplaceReferenceTables,
    SourceDateScope,
)
from eve_ingest.raw_objects import AcquiredRawObject, AcquisitionStatus, UpdateMode
from eve_ingest.raw_objects.http_models import RevalidationMetadata
from eve_ingest.raw_objects.ledger.models import RawObjectEntry, RawObjectRef, RawObjectVersion
from tests.sources.everef.conftest import make_cache_result

from .conftest import ATTACH, create_lock_token


@pytest.mark.real_duckdb
def test_append_snapshot_success(shared_con) -> None:
    spec = DatasetPublisherSpec(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        data_tables=(RawDuckLakeTable.MARKET_ORDERS,),
        provenance_tables=(RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,),
        publication_scope=SourceDateScope("market_orders"),
        write_policy=AppendSnapshotRows(),
    )
    raw_object = make_cache_result(
        "/tmp/test_snap.csv",
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://example.com/market-orders/snap.csv.bz2",
        identity_hash="hash-snap-1",
    )
    sql_source = SqlSource(
        sql="""SELECT 1 AS order_id, 34 AS type_id, 10000001 AS region_id, 9.99 AS price,
                      'soid-snap-1' AS source_ref_id,
                      DATE '2026-01-01' AS source_market_date,
                      TIMESTAMP '2026-01-01 00:00:00' AS snapshot_ts
               UNION ALL
               SELECT 2, 35, 10000002, 19.99,
                      'soid-snap-1',
                      DATE '2026-01-01',
                      TIMESTAMP '2026-01-01 00:00:00'"""
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

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)
        result = service.append_snapshot(prepared, ctx=prep_ctx, source_ref_id="soid-snap-1")

    assert result.success is True
    assert result.source_date == "2026-01-01"
    assert len(result.write_metrics) == 1
    assert result.write_metrics[0].inserted_rows == 2

    rows = shared_con.execute(
        'SELECT order_id, price, source_ref_id FROM "memory"."raw"."raw_market_orders" ORDER BY order_id'
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] == (1, 9.99, "soid-snap-1")
    assert rows[1] == (2, 19.99, "soid-snap-1")

    prov_rows = shared_con.execute(
        'SELECT source_ref_id, status FROM "memory"."raw"."raw_market_orders_objects"'
    ).fetchall()
    assert len(prov_rows) == 1
    assert prov_rows[0] == ("soid-snap-1", "ingested")


@pytest.mark.real_duckdb
def test_append_snapshot_skip_on_matching_sha(shared_con) -> None:
    spec = DatasetPublisherSpec(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        data_tables=(RawDuckLakeTable.MARKET_ORDERS,),
        provenance_tables=(RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,),
        publication_scope=SourceDateScope("market_orders"),
        write_policy=AppendSnapshotRows(),
    )
    raw_object = make_cache_result(
        "/tmp/test_skip.csv",
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://example.com/market-orders/skip.csv.bz2",
        identity_hash="hash-skip-1",
    )
    sql_source = SqlSource(
        sql="""SELECT 1 AS order_id, 34 AS type_id, 9.99 AS price,
                      'soid-skip' AS source_ref_id,
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

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        first = service.append_snapshot(prepared, ctx=prep_ctx, source_ref_id="soid-skip")

    assert first.success is True
    assert len(first.write_metrics) == 1
    assert first.write_metrics[0].inserted_rows == 1

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        second = service.append_snapshot(prepared, ctx=prep_ctx, source_ref_id="soid-skip")

    assert second.success is True
    assert second.write_metrics == ()

    rows = shared_con.execute(
        'SELECT COUNT(*) FROM "memory"."raw"."raw_market_orders" WHERE source_ref_id = \'soid-skip\''
    ).fetchone()
    assert rows == (1,)


@pytest.mark.real_duckdb
def test_append_snapshot_immutable_violation(shared_con) -> None:
    spec = DatasetPublisherSpec(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        data_tables=(RawDuckLakeTable.MARKET_ORDERS,),
        provenance_tables=(RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,),
        publication_scope=SourceDateScope("market_orders"),
        write_policy=AppendSnapshotRows(),
    )

    ref = RawObjectRef(
        source_name="everef",
        dataset_name="market-orders",
        identity_hash="hash-immutable",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        update_mode=UpdateMode.SNAPSHOT,
    )
    entry = RawObjectEntry(
        id="obj-immutable",
        ref=ref,
        created_at=datetime(2026, 1, 2, 11, 1, 55, tzinfo=UTC),
    )
    revalidation = RevalidationMetadata(content_length=100, last_modified="2026-01-02T11:01:55Z")

    raw_v1 = AcquiredRawObject(
        status=AcquisitionStatus.STORED,
        raw_object=entry,
        version=RawObjectVersion(
            id="ver-1",
            raw_object_id="obj-immutable",
            source_url="https://example.com/market-orders/immutable.csv.bz2",
            fetched_at=datetime(2026, 1, 2, 11, 1, 55, tzinfo=UTC),
            revalidation=revalidation,
            sha256="abc123",
            local_path="/tmp/immutable.csv",
            storage_encoding="bz2",
            version_number=1,
        ),
    )
    sql_source = SqlSource(
        sql="""SELECT 1 AS order_id, 34 AS type_id, 9.99 AS price,
                      'soid-immutable' AS source_ref_id,
                      DATE '2026-01-01' AS source_market_date,
                      TIMESTAMP '2026-01-01 00:00:00' AS snapshot_ts"""
    )
    prepared_v1 = PreparedSnapshotSqlSource(
        raw_object=raw_v1,
        source_system="everef",
        endpoint="market_orders",
        source_market_date=date(2026, 1, 1),
        snapshot_ts=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        table=RawDuckLakeTable.MARKET_ORDERS,
        sql_source=sql_source,
    )

    raw_v2 = AcquiredRawObject(
        status=AcquisitionStatus.STORED,
        raw_object=entry,
        version=RawObjectVersion(
            id="ver-2",
            raw_object_id="obj-immutable",
            source_url="https://example.com/market-orders/immutable.csv.bz2",
            fetched_at=datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC),
            revalidation=revalidation,
            sha256="def456",
            local_path="/tmp/immutable.csv",
            storage_encoding="bz2",
            version_number=2,
        ),
    )
    prepared_v2 = PreparedSnapshotSqlSource(
        raw_object=raw_v2,
        source_system="everef",
        endpoint="market_orders",
        source_market_date=date(2026, 1, 1),
        snapshot_ts=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        table=RawDuckLakeTable.MARKET_ORDERS,
        sql_source=sql_source,
    )

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        first = service.append_snapshot(prepared_v1, ctx=prep_ctx, source_ref_id="soid-immutable")
    assert first.success is True

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        with pytest.raises(ValueError, match="Immutable snapshot source object changed"):
            service.append_snapshot(prepared_v2, ctx=prep_ctx, source_ref_id="soid-immutable")

    rows = shared_con.execute(
        'SELECT order_id FROM "memory"."raw"."raw_market_orders" WHERE source_ref_id = \'soid-immutable\''
    ).fetchall()
    assert len(rows) == 1


@pytest.mark.real_duckdb
def test_insert_missing_keys_success(shared_con) -> None:
    spec = DatasetPublisherSpec(
        dataset_name="market-history",
        update_mode=UpdateMode.MUTABLE,
        data_tables=(RawDuckLakeTable.MARKET_HISTORY,),
        provenance_tables=(RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS,),
        publication_scope=SourceDateScope("market_history"),
        write_policy=InsertMissingKeysAuthoritativePartition(
            key_columns=("date", "region_id", "type_id"),
        ),
    )
    raw_object = make_cache_result(
        "/tmp/test_auth.csv",
        dataset_name="market-history",
        identity_key={"source_date": "2026-01-01"},
        source_url="https://example.com/market-history/2026-01-01.csv.bz2",
        identity_hash="hash-auth-1",
        update_mode=UpdateMode.MUTABLE,
    )

    def _build_table(type_ids, averages):
        n = len(type_ids)
        table = pa.table(
            {
                "type_id": type_ids,
                "average": averages,
                "date": [date(2026, 1, 1)] * n,
                "region_id": [10000001] * n,
            }
        )
        table = table.append_column("source_ref_id", pa.array(["soid-auth"] * n, type=pa.utf8()))
        table = table.append_column("source_market_date", pa.array([date(2026, 1, 1)] * n, type=pa.date32()))
        return table

    first_table = _build_table([1, 2], [10.0, 20.0])
    first_prepared = PreparedAuthoritativeArrowSource(
        raw_object=raw_object,
        source_system="everef",
        endpoint="market_history",
        source_market_date=date(2026, 1, 1),
        table=RawDuckLakeTable.MARKET_HISTORY,
        arrow_table=first_table,
    )

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        first = service.insert_missing_keys(first_prepared, ctx=prep_ctx, source_ref_id="soid-auth")

    assert first.success is True
    assert first.source_date == "2026-01-01"
    assert len(first.write_metrics) == 1
    assert first.write_metrics[0].inserted_rows == 2
    assert first.write_metrics[0].matched_rows == 0

    second_table = _build_table([1, 2, 3], [10.0, 20.0, 30.0])
    second_prepared = PreparedAuthoritativeArrowSource(
        raw_object=raw_object,
        source_system="everef",
        endpoint="market_history",
        source_market_date=date(2026, 1, 1),
        table=RawDuckLakeTable.MARKET_HISTORY,
        arrow_table=second_table,
    )

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        second = service.insert_missing_keys(second_prepared, ctx=prep_ctx, source_ref_id="soid-auth")

    assert second.success is True
    assert len(second.write_metrics) == 1
    assert second.write_metrics[0].inserted_rows == 1
    assert second.write_metrics[0].matched_rows == 2

    rows = shared_con.execute(
        'SELECT type_id, average FROM "memory"."raw"."raw_market_history" ORDER BY type_id'
    ).fetchall()
    assert rows == [(1, 10.0), (2, 20.0), (3, 30.0)]


@pytest.mark.real_duckdb
def test_insert_missing_keys_wrong_policy(shared_con) -> None:
    spec = DatasetPublisherSpec(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        data_tables=(RawDuckLakeTable.MARKET_ORDERS,),
        provenance_tables=(RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,),
        publication_scope=SourceDateScope("market_orders"),
        write_policy=AppendSnapshotRows(),
    )
    raw_object = make_cache_result(
        "/tmp/test_wrong.csv",
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://example.com/market-orders/wrong.csv.bz2",
        identity_hash="hash-wrong-1",
    )
    table = pa.table({"type_id": [1], "average": [10.0], "source_market_date": [date(2026, 1, 1)]})
    table = table.append_column("source_ref_id", pa.array(["soid-wrong"], type=pa.utf8()))
    prepared = PreparedAuthoritativeArrowSource(
        raw_object=raw_object,
        source_system="everef",
        endpoint="market_history",
        source_market_date=date(2026, 1, 1),
        table=RawDuckLakeTable.MARKET_HISTORY,
        arrow_table=table,
    )

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        with pytest.raises(TypeError, match="not configured for insert-missing-keys"):
            service.insert_missing_keys(prepared, ctx=prep_ctx)


@pytest.mark.real_duckdb
def test_replace_tables_success(shared_con) -> None:
    spec = DatasetPublisherSpec(
        dataset_name="reference-data",
        update_mode=UpdateMode.SNAPSHOT,
        data_tables=(RawDuckLakeTable.REFERENCE_TYPES, RawDuckLakeTable.REFERENCE_REGIONS),
        provenance_tables=(RawDuckLakeProvenanceTable.REFERENCE_OBJECTS,),
        publication_scope=SourceDateScope("references"),
        write_policy=ReplaceReferenceTables(),
    )
    raw_object = make_cache_result(
        "/tmp/test_ref.tar.xz",
        dataset_name="reference-data",
        identity_key={"source_date": "latest"},
        source_url="https://example.com/reference-data/latest.tar.xz",
        identity_hash="hash-ref-1",
        update_mode=UpdateMode.MUTABLE,
    )
    types_table = pa.table({"type_id": [1, 2], "name_en": ["foo", "bar"]})
    regions_table = pa.table({"region_id": [10000001, 10000002], "name_en": ["Region A", "Region B"]})
    prepared_tables = [
        PreparedReferenceTableSource(
            raw_object=raw_object,
            source_system="everef",
            endpoint="reference_data",
            table=RawDuckLakeTable.REFERENCE_TYPES,
            arrow_table=types_table,
        ),
        PreparedReferenceTableSource(
            raw_object=raw_object,
            source_system="everef",
            endpoint="reference_data",
            table=RawDuckLakeTable.REFERENCE_REGIONS,
            arrow_table=regions_table,
        ),
    ]

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        result = service.replace_tables(
            raw_object=raw_object,
            source_system="everef",
            endpoint="reference_data",
            source_market_date=date(2026, 1, 1),
            prepared_tables=prepared_tables,
            provenance_table=RawDuckLakeProvenanceTable.REFERENCE_OBJECTS,
            ctx=prep_ctx,
        )

    assert result.success is True
    assert result.source_date == "latest"
    assert len(result.write_metrics) == 2

    types_rows = shared_con.execute(
        'SELECT type_id, name_en FROM "memory"."raw"."raw_reference_types" ORDER BY type_id'
    ).fetchall()
    assert types_rows == [(1, "foo"), (2, "bar")]

    regions_rows = shared_con.execute(
        'SELECT region_id, name_en FROM "memory"."raw"."raw_reference_regions" ORDER BY region_id'
    ).fetchall()
    assert regions_rows == [(10000001, "Region A"), (10000002, "Region B")]


@pytest.mark.real_duckdb
def test_replace_tables_wrong_policy(shared_con) -> None:
    spec = DatasetPublisherSpec(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        data_tables=(RawDuckLakeTable.MARKET_ORDERS,),
        provenance_tables=(RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,),
        publication_scope=SourceDateScope("market_orders"),
        write_policy=AppendSnapshotRows(),
    )
    raw_object = make_cache_result(
        "/tmp/test_wrong_r.csv",
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://example.com/market-orders/wrong_r.csv.bz2",
        identity_hash="hash-wrong-r",
    )
    prepared_table = PreparedReferenceTableSource(
        raw_object=raw_object,
        source_system="everef",
        endpoint="reference_data",
        table=RawDuckLakeTable.REFERENCE_TYPES,
        arrow_table=pa.table({"type_id": [1], "name_en": ["foo"]}),
    )

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        with pytest.raises(TypeError, match="not configured for reference-table replacement"):
            service.replace_tables(
                raw_object=raw_object,
                source_system="everef",
                endpoint="reference_data",
                source_market_date=date(2026, 1, 1),
                prepared_tables=[prepared_table],
                provenance_table=RawDuckLakeProvenanceTable.REFERENCE_OBJECTS,
                ctx=prep_ctx,
            )


@pytest.mark.real_duckdb
def test_provenance_error_path(shared_con) -> None:
    spec = DatasetPublisherSpec(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        data_tables=(RawDuckLakeTable.MARKET_ORDERS,),
        provenance_tables=(RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,),
        publication_scope=SourceDateScope("market_orders"),
        write_policy=AppendSnapshotRows(),
    )
    raw_object = make_cache_result(
        "/tmp/test_err.csv",
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://example.com/market-orders/err.csv.bz2",
        identity_hash="hash-err-1",
    )
    sql_source = SqlSource(
        sql="""SELECT 1 AS order_id, 34 AS type_id, 9.99 AS price,
                      'soid-err' AS source_ref_id,
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

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        result = service.append_snapshot(prepared, ctx=prep_ctx, source_ref_id="soid-err")
    assert result.success is True

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        service.mark_failed(
            "soid-err",
            table=RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,
            reason="simulated error after commit",
        )

    prov_rows = shared_con.execute(
        'SELECT source_ref_id, status, status_reason FROM "memory"."raw"."raw_market_orders_objects"'
    ).fetchall()
    assert len(prov_rows) == 1
    assert prov_rows[0][0] == "soid-err"
    assert prov_rows[0][1] == "failed"
    assert prov_rows[0][2] == "simulated error after commit"


@pytest.mark.real_duckdb
def test_provenance_rollback_on_write_failure(shared_con) -> None:
    spec = DatasetPublisherSpec(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        data_tables=(RawDuckLakeTable.MARKET_ORDERS,),
        provenance_tables=(RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,),
        publication_scope=SourceDateScope("market_orders"),
        write_policy=AppendSnapshotRows(),
    )
    raw_object = make_cache_result(
        "/tmp/test_rollback.csv",
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://example.com/market-orders/rollback.csv.bz2",
        identity_hash="hash-rollback-1",
    )
    sql_source = SqlSource(
        sql="""SELECT 1 AS order_id, 34 AS type_id, 10000001 AS region_id, 9.99 AS price,
                      'soid-rollback' AS source_ref_id,
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

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(
            session=session, lock_token=lock_token, declared_policy=spec.writer_mode, dataset_name=spec.dataset_name
        )
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(raw_tables=raw_tables, provenance=provenance, session=session, spec=spec)

        def _simulate_write_failure(*, source_name: str, table: RawDuckLakeTable) -> DuckLakeWriteMetrics:
            raise RuntimeError("simulated write failure")

        raw_tables.append_snapshot_prepared_source = _simulate_write_failure  # type: ignore

        with pytest.raises(RuntimeError, match="simulated write failure"):
            service.append_snapshot(prepared, ctx=prep_ctx, source_ref_id="soid-rollback")

    prov_rows = shared_con.execute(
        'SELECT source_ref_id, status FROM "memory"."raw"."raw_market_orders_objects"'
    ).fetchall()
    assert prov_rows == []

    rows = shared_con.execute(
        'SELECT COUNT(*) FROM "memory"."raw"."raw_market_orders" WHERE source_ref_id = \'soid-rollback\''
    ).fetchone()
    assert rows == (0,)
