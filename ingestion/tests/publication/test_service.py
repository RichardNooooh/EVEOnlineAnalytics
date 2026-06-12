"""Tests for PublicationService - provenance lifecycle and publication paths."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, call, create_autospec

import pyarrow as pa
import pytest
from eve_ingest.ducklake.provenance import SourceObjectProvenanceRepository
from eve_ingest.ducklake.raw_publish import RawTablePublisher
from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriteMetrics,
    DuckLakeWriterMode,
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
)
from eve_ingest.raw_objects.models import AcquiredRawObject


class FakeSourceObjectProvenanceRepository(SourceObjectProvenanceRepository):
    def __init__(self, sha256_for: dict[str, str | None] | None = None) -> None:
        self.records: list[tuple[dict, RawDuckLakeProvenanceTable]] = []
        self.parsed: list[str] = []
        self.ingested: list[str] = []
        self._sha256_for = sha256_for or {}

    def ingested_sha256(self, source_ref_id: str, table: RawDuckLakeProvenanceTable) -> str | None:
        return self._sha256_for.get(source_ref_id)

    def record_source_object(self, metadata: dict, *, table: RawDuckLakeProvenanceTable) -> None:
        self.records.append((metadata, table))

    def mark_parsed(self, source_ref_id: str, *, table: RawDuckLakeProvenanceTable) -> None:
        self.parsed.append(source_ref_id)

    def mark_ingested(self, source_ref_id: str, *, table: RawDuckLakeProvenanceTable) -> None:
        self.ingested.append(source_ref_id)


@pytest.fixture
def mock_raw_tables() -> MagicMock:
    return create_autospec(RawTablePublisher, instance=True)


@pytest.fixture
def mock_provenance() -> MagicMock:
    return create_autospec(SourceObjectProvenanceRepository, instance=True)


@pytest.fixture
def mock_session() -> MagicMock:
    return create_autospec(DuckLakeSession, instance=True)


@pytest.fixture
def mock_prep_ctx() -> MagicMock:
    return create_autospec(SourcePreparationContext, instance=True)


@pytest.fixture
def append_snapshot_spec() -> DatasetPublisherSpec:
    spec = create_autospec(DatasetPublisherSpec, instance=True)
    spec.write_policy = AppendSnapshotRows(immutable_source_object=True)
    spec.dataset_name = "market_orders"
    return spec


@pytest.fixture
def insert_missing_keys_spec() -> DatasetPublisherSpec:
    spec = create_autospec(DatasetPublisherSpec, instance=True)
    spec.write_policy = InsertMissingKeysAuthoritativePartition(key_columns=("type_id", "region_id"))
    spec.dataset_name = "market_history"
    return spec


@pytest.fixture
def replace_tables_spec() -> DatasetPublisherSpec:
    spec = create_autospec(DatasetPublisherSpec, instance=True)
    spec.write_policy = ReplaceReferenceTables()
    spec.dataset_name = "references"
    return spec


@pytest.fixture
def service(
    mock_raw_tables: MagicMock,
    mock_provenance: MagicMock,
    mock_session: MagicMock,
    append_snapshot_spec: DatasetPublisherSpec,
) -> PublicationService:
    return PublicationService(
        raw_tables=mock_raw_tables,
        provenance=mock_provenance,
        session=mock_session,
        spec=append_snapshot_spec,
    )


def _make_mock_raw_object(**overrides: object) -> MagicMock:
    raw = create_autospec(AcquiredRawObject, instance=True)
    raw.identity_key = {"source_date": overrides.get("source_date", "2026-01-01")}
    ver = MagicMock()
    ver.source_url = overrides.get("source_url", "https://example.com/file.csv")
    ver.sha256 = overrides.get("sha256", "a" * 64)
    ver.fetched_at = datetime(2026, 1, 1, 12, 0, 0)
    ver.revalidation = MagicMock()
    ver.revalidation.last_modified = "Mon, 01 Jan 2026 12:00:00 GMT"
    ver.revalidation.content_length = 100
    raw.version = ver
    raw.path = "/data/raw/file.csv"
    return raw


class TestPublicationServiceAppendSnapshot:
    # ------------------------------------------------------------------
    # Success path
    # ------------------------------------------------------------------

    def test_append_snapshot_success(
        self,
        mock_raw_tables: MagicMock,
        mock_session: MagicMock,
        mock_prep_ctx: MagicMock,
        append_snapshot_spec: DatasetPublisherSpec,
    ) -> None:
        provenance = FakeSourceObjectProvenanceRepository(sha256_for={"soid-1": None})
        service = PublicationService(
            raw_tables=mock_raw_tables,
            provenance=provenance,
            session=mock_session,
            spec=append_snapshot_spec,
        )
        raw_object = _make_mock_raw_object()
        prepared = PreparedSnapshotSqlSource(
            raw_object=raw_object,
            source_system="everef",
            endpoint="market_orders",
            source_market_date=date(2026, 1, 1),
            snapshot_ts=datetime(2026, 1, 1, 12, 0, 0),
            table=RawDuckLakeTable.MARKET_ORDERS,
            sql_source=SqlSource(sql="SELECT 1 AS order_id, 'soid-1' AS source_ref_id"),
        )
        mock_prep_ctx.source_ref_id.return_value = "soid-1"
        metrics = DuckLakeWriteMetrics(
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
            attempted_rows=1,
            inserted_rows=1,
            matched_rows=0,
            replaced_rows=0,
        )
        mock_raw_tables.append_snapshot_prepared_source.return_value = metrics
        mock_prep_ctx.prepare_sql_source.return_value.__enter__.return_value = "_sql_view"
        mock_session.transaction.return_value.__enter__.return_value = None

        result = service.append_snapshot(prepared, ctx=mock_prep_ctx, source_ref_id="soid-1")

        assert result.success is True
        assert result.source_date == "2026-01-01"
        assert result.write_metrics == (metrics,)

        metadata = mock_prep_ctx.build_source_object_metadata.return_value
        assert provenance.records == [(metadata, RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS)]
        assert provenance.parsed == ["soid-1"]
        assert provenance.ingested == ["soid-1"]
        mock_prep_ctx.prepare_sql_source.assert_called_once_with(prepared.sql_source)
        mock_session.transaction.assert_called_once()
        mock_raw_tables.append_snapshot_prepared_source.assert_called_once_with(
            source_name="_sql_view",
            table=RawDuckLakeTable.MARKET_ORDERS,
        )

    # ------------------------------------------------------------------
    # Already ingested with matching SHA - skip
    # ------------------------------------------------------------------

    def test_append_snapshot_already_ingested_skips(
        self,
        service: PublicationService,
        mock_provenance: MagicMock,
        mock_prep_ctx: MagicMock,
    ) -> None:
        raw_object = _make_mock_raw_object(sha256="a" * 64)
        prepared = PreparedSnapshotSqlSource(
            raw_object=raw_object,
            source_system="everef",
            endpoint="market_orders",
            source_market_date=date(2026, 1, 1),
            snapshot_ts=datetime(2026, 1, 1, 12, 0, 0),
            table=RawDuckLakeTable.MARKET_ORDERS,
            sql_source=SqlSource(sql="SELECT 1"),
        )
        mock_provenance.ingested_sha256.return_value = "a" * 64

        result = service.append_snapshot(prepared, ctx=mock_prep_ctx, source_ref_id="soid-1")

        assert result.success is True
        assert result.source_date == "2026-01-01"
        assert result.write_metrics == ()

        assert mock_provenance.ingested_sha256.call_count == 1
        mock_prep_ctx.build_source_object_metadata.assert_not_called()
        mock_prep_ctx.prepare_sql_source.assert_not_called()
        mock_provenance.mark_parsed.assert_not_called()
        mock_provenance.mark_ingested.assert_not_called()

    # ------------------------------------------------------------------
    # Already ingested with mismatched SHA and immutable_source_object
    # ------------------------------------------------------------------

    def test_append_snapshot_mismatched_sha_raises_value_error(
        self,
        service: PublicationService,
        mock_provenance: MagicMock,
        mock_prep_ctx: MagicMock,
    ) -> None:
        raw_object = _make_mock_raw_object(sha256="b" * 64)
        prepared = PreparedSnapshotSqlSource(
            raw_object=raw_object,
            source_system="everef",
            endpoint="market_orders",
            source_market_date=date(2026, 1, 1),
            snapshot_ts=datetime(2026, 1, 1, 12, 0, 0),
            table=RawDuckLakeTable.MARKET_ORDERS,
            sql_source=SqlSource(sql="SELECT 1"),
        )
        mock_provenance.ingested_sha256.return_value = "a" * 64

        with pytest.raises(ValueError, match="Immutable snapshot source object changed after ingestion"):
            service.append_snapshot(prepared, ctx=mock_prep_ctx, source_ref_id="soid-1")

    # ------------------------------------------------------------------
    # Wrong policy type
    # ------------------------------------------------------------------

    def test_append_snapshot_wrong_policy_raises_type_error(
        self,
        mock_raw_tables: MagicMock,
        mock_provenance: MagicMock,
        mock_session: MagicMock,
        mock_prep_ctx: MagicMock,
    ) -> None:
        service = PublicationService(
            raw_tables=mock_raw_tables,
            provenance=mock_provenance,
            session=mock_session,
            spec=create_autospec(
                DatasetPublisherSpec, instance=True, dataset_name="test", write_policy=ReplaceReferenceTables()
            ),
        )
        prepared = create_autospec(PreparedSnapshotSqlSource, instance=True)

        with pytest.raises(TypeError, match="not configured for append snapshot publication"):
            service.append_snapshot(prepared, ctx=mock_prep_ctx)


class TestPublicationServiceInsertMissingKeys:
    # ------------------------------------------------------------------
    # Success path
    # ------------------------------------------------------------------

    def test_insert_missing_keys_success(
        self,
        mock_raw_tables: MagicMock,
        mock_session: MagicMock,
        insert_missing_keys_spec: DatasetPublisherSpec,
    ) -> None:
        provenance = FakeSourceObjectProvenanceRepository()
        mock_prep_ctx = create_autospec(SourcePreparationContext, instance=True)
        service = PublicationService(
            raw_tables=mock_raw_tables,
            provenance=provenance,
            session=mock_session,
            spec=insert_missing_keys_spec,
        )

        raw_object = _make_mock_raw_object()
        arrow_table = pa.table({"type_id": [1], "region_id": [2], "value": [99.5]})
        prepared = PreparedAuthoritativeArrowSource(
            raw_object=raw_object,
            source_system="everef",
            endpoint="market_history",
            source_market_date=date(2026, 1, 1),
            table=RawDuckLakeTable.MARKET_HISTORY,
            arrow_table=arrow_table,
        )

        mock_prep_ctx.source_ref_id.return_value = "soid-1"
        metrics = DuckLakeWriteMetrics(
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            attempted_rows=1,
            inserted_rows=1,
            matched_rows=0,
            replaced_rows=0,
        )
        mock_raw_tables.write_prepared_source.return_value = metrics
        mock_prep_ctx.prepare_arrow_source.return_value.__enter__.return_value = "_arrow_view"
        mock_session.transaction.return_value.__enter__.return_value = None

        result = service.insert_missing_keys(prepared, ctx=mock_prep_ctx, source_ref_id="soid-1")

        assert result.success is True
        assert result.source_date == "2026-01-01"
        assert result.write_metrics == (metrics,)

        metadata = mock_prep_ctx.build_source_object_metadata.return_value
        assert provenance.records == [(metadata, RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS)]
        assert provenance.parsed == ["soid-1"]
        assert provenance.ingested == ["soid-1"]
        mock_prep_ctx.prepare_arrow_source.assert_called_once_with(arrow_table)
        mock_session.transaction.assert_called_once()
        mock_raw_tables.write_prepared_source.assert_called_once_with(
            arrow_table,
            source_name="_arrow_view",
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=("type_id", "region_id"),
        )

    # ------------------------------------------------------------------
    # Wrong policy type
    # ------------------------------------------------------------------

    def test_insert_missing_keys_wrong_policy_raises_type_error(
        self,
        mock_raw_tables: MagicMock,
        mock_provenance: MagicMock,
        mock_session: MagicMock,
        mock_prep_ctx: MagicMock,
    ) -> None:
        service = PublicationService(
            raw_tables=mock_raw_tables,
            provenance=mock_provenance,
            session=mock_session,
            spec=create_autospec(
                DatasetPublisherSpec, instance=True, dataset_name="test", write_policy=AppendSnapshotRows()
            ),
        )
        prepared = create_autospec(PreparedAuthoritativeArrowSource, instance=True)

        with pytest.raises(TypeError, match="not configured for insert-missing-keys publication"):
            service.insert_missing_keys(prepared, ctx=mock_prep_ctx)


class TestPublicationServiceReplaceTables:
    # ------------------------------------------------------------------
    # Success path
    # ------------------------------------------------------------------

    def test_replace_tables_success(
        self,
        mock_raw_tables: MagicMock,
        mock_session: MagicMock,
        replace_tables_spec: DatasetPublisherSpec,
    ) -> None:
        provenance = FakeSourceObjectProvenanceRepository()
        mock_prep_ctx = create_autospec(SourcePreparationContext, instance=True)
        service = PublicationService(
            raw_tables=mock_raw_tables,
            provenance=provenance,
            session=mock_session,
            spec=replace_tables_spec,
        )

        raw_object = _make_mock_raw_object(source_date="2026-01-15")
        arrow_table_a = pa.table({"type_id": [1], "name_en": ["foo"]})
        arrow_table_b = pa.table({"type_id": [2], "name_en": ["bar"]})

        pt_a = PreparedReferenceTableSource(
            raw_object=raw_object,
            source_system="everef",
            endpoint="references",
            table=RawDuckLakeTable.REFERENCE_TYPES,
            arrow_table=arrow_table_a,
        )
        pt_b = PreparedReferenceTableSource(
            raw_object=raw_object,
            source_system="everef",
            endpoint="references",
            table=RawDuckLakeTable.REFERENCE_CATEGORIES,
            arrow_table=arrow_table_b,
        )

        mock_prep_ctx.source_ref_id.return_value = "soid-1"
        metrics_a = DuckLakeWriteMetrics(
            table=RawDuckLakeTable.REFERENCE_TYPES,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
            attempted_rows=1,
            inserted_rows=1,
            matched_rows=0,
            replaced_rows=0,
        )
        metrics_b = DuckLakeWriteMetrics(
            table=RawDuckLakeTable.REFERENCE_CATEGORIES,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
            attempted_rows=1,
            inserted_rows=1,
            matched_rows=0,
            replaced_rows=0,
        )
        mock_raw_tables.write_prepared_source.side_effect = [metrics_a, metrics_b]
        mock_prep_ctx.prepare_arrow_source.return_value.__enter__.side_effect = ["_view_a", "_view_b"]
        mock_session.transaction.return_value.__enter__.return_value = None

        result = service.replace_tables(
            raw_object=raw_object,
            source_system="everef",
            endpoint="references",
            source_market_date=date(2026, 1, 15),
            prepared_tables=[pt_a, pt_b],
            provenance_table=RawDuckLakeProvenanceTable.REFERENCE_OBJECTS,
            source_ref_id="soid-1",
            ctx=mock_prep_ctx,
        )

        assert result.success is True
        assert result.source_date == "2026-01-15"
        assert result.write_metrics == (metrics_a, metrics_b)

        metadata = mock_prep_ctx.build_source_object_metadata.return_value
        assert provenance.records == [(metadata, RawDuckLakeProvenanceTable.REFERENCE_OBJECTS)]
        assert provenance.parsed == ["soid-1"]
        assert provenance.ingested == ["soid-1"]

        # Each table prepared via arrow
        assert mock_prep_ctx.prepare_arrow_source.call_args_list == [
            call(arrow_table_a),
            call(arrow_table_b),
        ]

        # Each table written with REPLACE_TABLE
        assert mock_raw_tables.write_prepared_source.call_args_list == [
            call(
                arrow_table_a,
                source_name="_view_a",
                table=RawDuckLakeTable.REFERENCE_TYPES,
                mode=DuckLakeWriterMode.REPLACE_TABLE,
            ),
            call(
                arrow_table_b,
                source_name="_view_b",
                table=RawDuckLakeTable.REFERENCE_CATEGORIES,
                mode=DuckLakeWriterMode.REPLACE_TABLE,
            ),
        ]

    # ------------------------------------------------------------------
    # Wrong policy type
    # ------------------------------------------------------------------

    def test_replace_tables_wrong_policy_raises_type_error(
        self,
        mock_raw_tables: MagicMock,
        mock_provenance: MagicMock,
        mock_session: MagicMock,
        mock_prep_ctx: MagicMock,
    ) -> None:
        service = PublicationService(
            raw_tables=mock_raw_tables,
            provenance=mock_provenance,
            session=mock_session,
            spec=create_autospec(
                DatasetPublisherSpec, instance=True, dataset_name="test", write_policy=AppendSnapshotRows()
            ),
        )
        raw_object = _make_mock_raw_object()

        with pytest.raises(TypeError, match="not configured for reference-table replacement"):
            service.replace_tables(
                raw_object=raw_object,
                source_system="everef",
                endpoint="references",
                source_market_date=date(2026, 1, 15),
                prepared_tables=[],
                provenance_table=RawDuckLakeProvenanceTable.REFERENCE_OBJECTS,
                ctx=mock_prep_ctx,
            )
