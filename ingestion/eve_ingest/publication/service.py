from __future__ import annotations

import logging
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date

from eve_ingest.ducklake.provenance import SourceObjectProvenanceRepository
from eve_ingest.ducklake.raw_publish import RawTablePublisher
from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriteMetrics,
    DuckLakeWriterMode,
    RawDuckLakeProvenanceTable,
    provenance_table_for_data_table,
)
from eve_ingest.ducklake.session import DuckLakeSession
from eve_ingest.publication.source_prep import SourcePreparationContext
from eve_ingest.publication.prepared_source import (
    PreparedAuthoritativeArrowSource,
    PreparedReferenceTableSource,
    PreparedSnapshotSqlSource,
)
from eve_ingest.publication.results import PublishResult
from eve_ingest.publication.specs import (
    AppendSnapshotRows,
    InsertMissingKeysAuthoritativePartition,
    ReplaceReferenceTables,
)
from eve_ingest.raw_objects.models import AcquiredRawObject

logger = logging.getLogger(__name__)


@dataclass
class PublicationService:
    """Provenance + raw table write lifecycle.

    Owns the publication lifecycle for source objects: records provenance,
    writes data to raw tables, and manages transaction boundaries. Source
    modules interact with this through ``PublishContext``, passing prepared
    source descriptors.
    """

    raw_tables: RawTablePublisher
    provenance: SourceObjectProvenanceRepository
    session: DuckLakeSession
    spec: object

    ##############################
    # Provenance Lifecycle
    ##############################

    def record_provenance(self, soid: str, metadata: dict, *, table: RawDuckLakeProvenanceTable) -> None:
        self.provenance.record_source_object(metadata, table=table)

    def mark_parsed(self, soid: str, *, table: RawDuckLakeProvenanceTable) -> None:
        self.provenance.mark_parsed(soid, table=table)

    def mark_ingested(self, soid: str, *, table: RawDuckLakeProvenanceTable) -> None:
        self.provenance.mark_ingested(soid, table=table)

    def mark_failed(self, soid: str, *, table: RawDuckLakeProvenanceTable, reason: str) -> None:
        self.provenance.mark_failed(soid, table=table, reason=reason)

    ##############################
    # Snapshot SQL Publication
    ##############################

    def append_snapshot(
        self,
        prepared: PreparedSnapshotSqlSource,
        *,
        ctx: SourcePreparationContext,
        source_ref_id: str | None = None,
    ) -> PublishResult:
        policy = self.spec.write_policy
        if not isinstance(policy, AppendSnapshotRows):
            raise TypeError(f"Dataset {self.spec.dataset_name} is not configured for append snapshot publication")

        source_date = str(prepared.raw_object.identity_key.get("source_date", "unknown"))
        soid = source_ref_id or ctx.source_ref_id(
            source_system=prepared.source_system,
            endpoint=prepared.endpoint,
            source_url=prepared.raw_object.version.source_url,
        )
        provenance_table = provenance_table_for_data_table(prepared.table)

        existing_sha256 = self.provenance.ingested_sha256(
            source_ref_id=soid,
            table=provenance_table,
        )
        if existing_sha256 is not None:
            if existing_sha256 == prepared.raw_object.version.sha256:
                logger.info(
                    "Skipping already ingested snapshot source_date=%s table=%s source_ref_id=%s sha256_prefix=%s",
                    source_date,
                    prepared.table.value,
                    soid,
                    prepared.raw_object.version.sha256[:16],
                )
                return PublishResult(success=True, source_date=source_date)

            if policy.immutable_source_object:
                raise ValueError(
                    "Immutable snapshot source object changed after ingestion: "
                    f"source_date={source_date} table={prepared.table.value} source_ref_id={soid} "
                    f"existing_sha256_prefix={existing_sha256[:16]} "
                    f"new_sha256_prefix={prepared.raw_object.version.sha256[:16]}"
                )

        metadata = ctx.build_source_object_metadata(
            prepared.raw_object,
            prepared.source_system,
            prepared.endpoint,
            source_ref_id=soid,
            source_market_date=prepared.source_market_date,
            snapshot_ts=prepared.snapshot_ts,
        )

        with ctx.prepare_sql_source(prepared.sql_source) as source_name:
            with self.session.transaction():
                self.record_provenance(soid, metadata, table=provenance_table)
                self.mark_parsed(soid, table=provenance_table)

                metrics = self.raw_tables.append_snapshot_prepared_source(
                    source_name=source_name,
                    table=prepared.table,
                )

                self.mark_ingested(soid, table=provenance_table)

        if prepared.log_context:
            logger.debug(
                "Published snapshot source_date=%s table=%s source_ref_id=%s context=%s attempted_rows=%d inserted_rows=%d",
                source_date,
                prepared.table.value,
                soid,
                prepared.log_context,
                metrics.attempted_rows,
                metrics.inserted_rows,
            )

        return PublishResult(
            success=True,
            source_date=source_date,
            write_metrics=(metrics,),
        )

    ##############################
    # Insert Missing Keys Publication
    ##############################

    def insert_missing_keys(
        self,
        prepared: PreparedAuthoritativeArrowSource,
        *,
        ctx: SourcePreparationContext,
        source_ref_id: str | None = None,
    ) -> PublishResult:
        policy = self.spec.write_policy
        if not isinstance(policy, InsertMissingKeysAuthoritativePartition):
            raise TypeError(f"Dataset {self.spec.dataset_name} is not configured for insert-missing-keys publication")

        source_date = str(prepared.raw_object.identity_key.get("source_date", "unknown"))
        soid = source_ref_id or ctx.source_ref_id(
            source_system=prepared.source_system,
            endpoint=prepared.endpoint,
            source_url=prepared.raw_object.version.source_url,
        )
        provenance_table = provenance_table_for_data_table(prepared.table)

        metadata = ctx.build_source_object_metadata(
            prepared.raw_object,
            prepared.source_system,
            prepared.endpoint,
            source_ref_id=soid,
            source_market_date=prepared.source_market_date,
            snapshot_ts=None,
        )

        with ctx.prepare_arrow_source(prepared.arrow_table) as source_name:
            with self.session.transaction():
                self.record_provenance(soid, metadata, table=provenance_table)
                self.mark_parsed(soid, table=provenance_table)

                metrics = self.raw_tables.write_prepared_source(
                    prepared.arrow_table,
                    source_name=source_name,
                    table=prepared.table,
                    mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
                    key_columns=policy.key_columns,
                )

                self.mark_ingested(soid, table=provenance_table)

        return PublishResult(
            success=True,
            source_date=source_date,
            write_metrics=(metrics,),
        )

    ##############################
    # Reference Table Replacement
    ##############################

    def replace_tables(
        self,
        raw_object: AcquiredRawObject,
        *,
        source_system: str,
        endpoint: str,
        source_market_date: date,
        prepared_tables: list[PreparedReferenceTableSource],
        provenance_table: RawDuckLakeProvenanceTable,
        source_ref_id: str | None = None,
        ctx: SourcePreparationContext,
    ) -> PublishResult:
        policy = self.spec.write_policy
        if not isinstance(policy, ReplaceReferenceTables):
            raise TypeError(f"Dataset {self.spec.dataset_name} is not configured for reference-table replacement")

        source_date = str(raw_object.identity_key.get("source_date", "unknown"))
        soid = source_ref_id or ctx.source_ref_id(
            source_system=source_system,
            endpoint=endpoint,
            source_url=raw_object.version.source_url,
        )

        metadata = ctx.build_source_object_metadata(
            raw_object,
            source_system,
            endpoint,
            source_ref_id=soid,
            source_market_date=source_market_date,
            snapshot_ts=None,
        )

        metrics: list[DuckLakeWriteMetrics] = []

        with ExitStack() as stack:
            entries: list[tuple[PreparedReferenceTableSource, str]] = []
            for pt in prepared_tables:
                source_name = stack.enter_context(ctx.prepare_arrow_source(pt.arrow_table))
                entries.append((pt, source_name))

            with self.session.transaction():
                self.record_provenance(soid, metadata, table=provenance_table)
                self.mark_parsed(soid, table=provenance_table)

                for pt, source_name in entries:
                    write_metrics = self.raw_tables.write_prepared_source(
                        pt.arrow_table,
                        source_name=source_name,
                        table=pt.table,
                        mode=DuckLakeWriterMode.REPLACE_TABLE,
                    )
                    logger.debug(
                        "Published reference table=%s rows=%d replaced_rows=%d",
                        pt.table.value,
                        pt.arrow_table.num_rows,
                        write_metrics.replaced_rows,
                    )
                    metrics.append(write_metrics)

                self.mark_ingested(soid, table=provenance_table)

        return PublishResult(
            success=True,
            source_date=source_date,
            write_metrics=tuple(metrics),
        )
