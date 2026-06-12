from __future__ import annotations

import bz2
from datetime import date
from typing import TYPE_CHECKING

import pytest
from eve_ingest.ducklake.provenance import SourceObjectProvenanceRepository
from eve_ingest.ducklake.raw_publish import RawTablePublisher
from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable, compute_source_ref_id
from eve_ingest.ducklake.session import DuckLakeSession
from eve_ingest.publication.context import PublishContext
from eve_ingest.publication.service import PublicationService
from eve_ingest.publication.source_prep import SourcePreparationContext
from eve_ingest.publication.specs import DatasetPublisherSpec, InsertMissingKeysAuthoritativePartition, SourceDateScope
from eve_ingest.raw_objects import UpdateMode
from eve_ingest.sources.everef.market_history import publish_one
from tests.sources.everef.conftest import make_cache_result

from .conftest import ATTACH, create_lock_token

if TYPE_CHECKING:
    from pathlib import Path


def _write_history_file(path: Path) -> None:
    path.write_bytes(
        bz2.compress(
            b"average,date,highest,lowest,order_count,volume,http_last_modified,region_id,type_id\n"
            b"9.99,2026-01-01,9.99,9.99,1,24,2026-01-02T11:01:55Z,10000001,19\n"
        )
    )


@pytest.mark.real_duckdb
def test_process_result_writes_and_merges_history_rows(shared_con, tmp_path: Path) -> None:
    file_path = tmp_path / "market-history-2026-01-01.csv.bz2"
    _write_history_file(file_path)

    result = make_cache_result(
        str(file_path),
        content_length=file_path.stat().st_size,
        last_modified="2026-01-02T11:01:55Z",
        source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
    )

    spec = DatasetPublisherSpec(
        dataset_name="market-history",
        update_mode=UpdateMode.MUTABLE,
        data_tables=(RawDuckLakeTable.MARKET_HISTORY,),
        provenance_tables=(RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS,),
        publication_scope=SourceDateScope("market_history"),
        write_policy=InsertMissingKeysAuthoritativePartition(key_columns=("date", "region_id", "type_id")),
    )

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(session, lock_token=lock_token)
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
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
            publication_scope="raw:market_history:source_date=2026-01-01",
        )
        first_outcome = publish_one(result, ctx)
        assert first_outcome.success is True
        assert len(first_outcome.write_metrics) == 1
        assert first_outcome.write_metrics[0].inserted_rows == 1
        assert first_outcome.write_metrics[0].matched_rows == 0

    expected_source_ref_id = compute_source_ref_id("everef", "market_history", result.version.source_url)
    prov_rows = shared_con.execute(
        f'SELECT source_ref_id, status FROM "memory"."raw"."{RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS.value}"'
    ).fetchall()
    assert prov_rows == [(expected_source_ref_id, "ingested")]

    lock_token = create_lock_token()
    with DuckLakeSession(ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(session, lock_token=lock_token)
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
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
            publication_scope="raw:market_history:source_date=2026-01-01",
        )
        second_outcome = publish_one(result, ctx)
        assert second_outcome.success is True
        assert len(second_outcome.write_metrics) == 1
        assert second_outcome.write_metrics[0].inserted_rows == 0
        assert second_outcome.write_metrics[0].matched_rows == 1

    rows = shared_con.execute(
        f'SELECT average, "date", region_id, type_id FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}"'
    ).fetchall()

    assert rows == [(9.99, date(2026, 1, 1), 10000001, 19)]
