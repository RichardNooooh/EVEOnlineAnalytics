from __future__ import annotations

import gzip
from datetime import UTC
from typing import TYPE_CHECKING

import pytest
from eve_ingest.ducklake.provenance import SourceObjectProvenanceRepository
from eve_ingest.ducklake.raw_publish import RawTablePublisher
from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable, compute_source_ref_id
from eve_ingest.ducklake.session import DuckLakeSession
from eve_ingest.publication.context import PublishContext
from eve_ingest.publication.service import PublicationService
from eve_ingest.publication.source_prep import SourcePreparationContext
from eve_ingest.publication.specs import AppendSnapshotRows, DatasetPublisherSpec, SourceDateScope
from eve_ingest.raw_objects import UpdateMode
from eve_ingest.sources.everef.fuzzwork_orders import publish_one
from tests.sources.everef.conftest import make_cache_result

from .conftest import ATTACH, create_lock_token

if TYPE_CHECKING:
    from pathlib import Path


def _write_orderset_file(path: Path, price: float) -> None:
    path.write_bytes(
        gzip.compress(
            (f"1\t34\t2026-01-01T00:00:00Z\tTrue\t10\t100\t1\t{price}\t60000001\t0\t30\t10000002\t161676\n").encode()
        )
    )


@pytest.mark.real_duckdb
def test_process_result_is_idempotent_for_same_fuzzwork_orders_source_object(shared_con, tmp_path: Path) -> None:
    file_path = tmp_path / "fuzzwork.csv.gz"
    _write_orderset_file(file_path, price=9.99)

    result = make_cache_result(
        str(file_path),
        content_length=file_path.stat().st_size,
        last_modified="2026-01-01T12:06:49Z",
        dataset_name="fuzzwork-orders",
        identity_key={"source_date": "2026-01-01", "order_set_id": "161676", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://data.everef.net/fuzzwork/ordersets/2026/2026-01-01/fuzzwork-orderset-161676-2026-01-01_00-00-00.csv.gz",
    )

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(session, lock_token=lock_token)
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        spec = DatasetPublisherSpec(
            dataset_name="fuzzwork-orders",
            update_mode=UpdateMode.SNAPSHOT,
            data_tables=(RawDuckLakeTable.FUZZWORK_ORDERS,),
            provenance_tables=(RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS,),
            publication_scope=SourceDateScope("fuzzwork_orders"),
            write_policy=AppendSnapshotRows(),
        )
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(
            raw_tables=raw_tables,
            provenance=provenance,
            session=session,
            spec=spec,
        )
        ctx = PublishContext(
            spec=spec,
            prep_ctx=prep_ctx,
            service=service,
            publication_scope="raw:fuzzwork_orders:source_date=2026-01-01",
        )
        first_outcome = publish_one(result, ctx)

    assert first_outcome.success is True
    assert first_outcome.source_date == "2026-01-01"
    assert len(first_outcome.write_metrics) == 1
    assert first_outcome.write_metrics[0].inserted_rows == 1
    assert first_outcome.write_metrics[0].matched_rows == 0

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(session, lock_token=lock_token)
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        spec = DatasetPublisherSpec(
            dataset_name="fuzzwork-orders",
            update_mode=UpdateMode.SNAPSHOT,
            data_tables=(RawDuckLakeTable.FUZZWORK_ORDERS,),
            provenance_tables=(RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS,),
            publication_scope=SourceDateScope("fuzzwork_orders"),
            write_policy=AppendSnapshotRows(),
        )
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(
            raw_tables=raw_tables,
            provenance=provenance,
            session=session,
            spec=spec,
        )
        ctx = PublishContext(
            spec=spec,
            prep_ctx=prep_ctx,
            service=service,
            publication_scope="raw:fuzzwork_orders:source_date=2026-01-01",
        )
        second_outcome = publish_one(result, ctx)

    assert second_outcome.success is True
    assert second_outcome.source_date == "2026-01-01"
    assert second_outcome.write_metrics == ()

    rows = shared_con.execute(
        f'SELECT order_id, price FROM "memory"."raw"."{RawDuckLakeTable.FUZZWORK_ORDERS.value}" ORDER BY price'
    ).fetchall()

    assert rows == [(1, 9.99)]


@pytest.mark.real_duckdb
def test_process_result_writes_native_tsv_columns_metadata_and_provenance(shared_con, tmp_path: Path) -> None:
    file_path = tmp_path / "fuzzwork.csv.gz"
    _write_orderset_file(file_path, price=12.34)

    result = make_cache_result(
        str(file_path),
        content_length=file_path.stat().st_size,
        last_modified="2026-01-01T12:06:49Z",
        dataset_name="fuzzwork-orders",
        identity_key={"source_date": "2026-01-01", "order_set_id": "161676", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://data.everef.net/fuzzwork/ordersets/2026/2026-01-01/fuzzwork-orderset-161676-2026-01-01_00-00-00.csv.gz",
    )

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(session, lock_token=lock_token)
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        spec = DatasetPublisherSpec(
            dataset_name="fuzzwork-orders",
            update_mode=UpdateMode.SNAPSHOT,
            data_tables=(RawDuckLakeTable.FUZZWORK_ORDERS,),
            provenance_tables=(RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS,),
            publication_scope=SourceDateScope("fuzzwork_orders"),
            write_policy=AppendSnapshotRows(),
        )
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(
            raw_tables=raw_tables,
            provenance=provenance,
            session=session,
            spec=spec,
        )
        ctx = PublishContext(
            spec=spec,
            prep_ctx=prep_ctx,
            service=service,
            publication_scope="raw:fuzzwork_orders:source_date=2026-01-01",
        )
        outcome = publish_one(result, ctx)

    assert outcome.success is True
    expected_source_ref_id = compute_source_ref_id("fuzzwork", "fuzzwork_orders", result.version.source_url)

    raw_rows = shared_con.execute(
        f'''SELECT order_id, order_set_id, issued, is_buy_order, source_ref_id, source_market_date, snapshot_ts
        FROM "memory"."raw"."{RawDuckLakeTable.FUZZWORK_ORDERS.value}"'''
    ).fetchall()
    assert len(raw_rows) == 1
    order_id, order_set_id, issued, is_buy_order, source_ref_id, source_market_date, snapshot_ts = raw_rows[0]
    assert order_id == 1
    assert order_set_id == 161676
    assert str(issued).startswith("2026-01-01 00:00:00")
    assert is_buy_order is True
    assert source_ref_id == expected_source_ref_id
    assert str(source_market_date) == "2026-01-01"
    assert snapshot_ts.astimezone(UTC).isoformat() == "2026-01-01T00:00:00+00:00"

    provenance_rows = shared_con.execute(
        f'''SELECT source_ref_id, status, source_market_date
        FROM "memory"."raw"."{RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS.value}"'''
    ).fetchall()
    assert provenance_rows == [(expected_source_ref_id, "ingested", source_market_date)]
