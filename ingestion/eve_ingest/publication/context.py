from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pyarrow as pa

from eve_ingest.ducklake.provenance import SourceObjectProvenanceRepository
from eve_ingest.ducklake.raw_publish import RawTablePublisher
from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriteMetrics,
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
    compute_source_object_id,
    provenance_table_for_data_table,
)
from eve_ingest.ducklake.session import DuckLakeSession, SqlSource
from eve_ingest.publication.results import PublishResult
from eve_ingest.publication.specs import (
    AppendSnapshotRows,
    DatasetPublisherSpec,
    InsertMissingKeysAuthoritativePartition,
    ReplaceReferenceTables,
)
from eve_ingest.raw_objects.models import CacheResult
from eve_ingest.sources.everef.provenance import build_source_object_metadata

logger = logging.getLogger(__name__)

##############################
# PublishContext
##############################


@dataclass
class PublishContext:
    spec: DatasetPublisherSpec
    session: DuckLakeSession
    raw_tables: RawTablePublisher
    provenance: SourceObjectProvenanceRepository
    publication_scope: str

    def source_object_id(
        self,
        *,
        source_system: str,
        endpoint: str,
        source_url: str,
    ) -> str:
        return compute_source_object_id(source_system, endpoint, source_url)

    def quote_sql_string(self, value: str) -> str:
        return self.session.quote_sql_string(value)

    ##############################
    # Snapshot SQL Publication
    ##############################

    def append_snapshot_sql(
        self,
        raw_object: CacheResult,
        *,
        source_system: str,
        endpoint: str,
        source_market_date: date,
        snapshot_ts: datetime,
        table: RawDuckLakeTable,
        sql_source: SqlSource,
        source_object_id: str | None = None,
        log_context: dict[str, Any] | None = None,
    ) -> PublishResult:
        policy = self.spec.write_policy
        if not isinstance(policy, AppendSnapshotRows):
            raise TypeError(f"Dataset {self.spec.dataset_name} is not configured for append snapshot publication")

        source_date = str(raw_object.identity_key.get("source_date", "unknown"))
        soid = source_object_id or self.source_object_id(
            source_system=source_system,
            endpoint=endpoint,
            source_url=raw_object.version.source_url,
        )
        provenance_table = provenance_table_for_data_table(table)

        existing_sha256 = self.provenance.ingested_sha256(
            source_object_id=soid,
            table=provenance_table,
        )
        if existing_sha256 is not None:
            if existing_sha256 == raw_object.version.sha256:
                logger.info(
                    "Skipping already ingested snapshot source_date=%s table=%s source_object_id=%s sha256_prefix=%s",
                    source_date,
                    table.value,
                    soid,
                    raw_object.version.sha256[:16],
                )
                return PublishResult(success=True, source_date=source_date)

            if policy.immutable_source_object:
                raise ValueError(
                    "Immutable snapshot source object changed after ingestion: "
                    f"source_date={source_date} table={table.value} source_object_id={soid} "
                    f"existing_sha256_prefix={existing_sha256[:16]} "
                    f"new_sha256_prefix={raw_object.version.sha256[:16]}"
                )

        metadata = build_source_object_metadata(
            raw_object,
            source_system,
            endpoint,
            source_market_date=source_market_date,
            snapshot_ts=snapshot_ts,
        )
        metadata["source_object_id"] = soid

        with self.session.prepare_sql_source(sql_source) as source_name:
            with self.session.transaction():
                self.provenance.record_source_object(metadata, table=provenance_table)
                self.provenance.mark_parsed(soid, table=provenance_table)

                metrics = self.raw_tables.append_snapshot_prepared_source(
                    source_name=source_name,
                    table=table,
                )

                self.provenance.mark_ingested(soid, table=provenance_table)

        if log_context:
            logger.debug(
                "Published snapshot source_date=%s table=%s source_object_id=%s context=%s attempted_rows=%d inserted_rows=%d",
                source_date,
                table.value,
                soid,
                log_context,
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

    def insert_missing_keys_arrow(
        self,
        raw_object: CacheResult,
        *,
        source_system: str,
        endpoint: str,
        source_market_date: date,
        table: RawDuckLakeTable,
        arrow_table: pa.Table,
        source_object_id: str | None = None,
    ) -> PublishResult:
        policy = self.spec.write_policy
        if not isinstance(policy, InsertMissingKeysAuthoritativePartition):
            raise TypeError(f"Dataset {self.spec.dataset_name} is not configured for insert-missing-keys publication")

        source_date = str(raw_object.identity_key.get("source_date", "unknown"))
        soid = source_object_id or self.source_object_id(
            source_system=source_system,
            endpoint=endpoint,
            source_url=raw_object.version.source_url,
        )
        provenance_table = provenance_table_for_data_table(table)

        metadata = build_source_object_metadata(
            raw_object,
            source_system,
            endpoint,
            source_market_date=source_market_date,
            snapshot_ts=None,
        )
        metadata["source_object_id"] = soid

        from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode

        with self.session.prepare_arrow_source(arrow_table) as source_name:
            with self.session.transaction():
                self.provenance.record_source_object(metadata, table=provenance_table)
                self.provenance.mark_parsed(soid, table=provenance_table)

                metrics = self.raw_tables.write_prepared_source(
                    arrow_table,
                    source_name=source_name,
                    table=table,
                    mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
                    key_columns=policy.key_columns,
                )

                self.provenance.mark_ingested(soid, table=provenance_table)

        return PublishResult(
            success=True,
            source_date=source_date,
            write_metrics=(metrics,),
        )

    ##############################
    # Reference Table Replacement
    ##############################

    def replace_reference_tables(
        self,
        raw_object: CacheResult,
        *,
        source_system: str,
        endpoint: str,
        source_market_date: date,
        prepared_tables: Sequence[tuple[str, RawDuckLakeTable, pa.Table, str]],
        provenance_table: RawDuckLakeProvenanceTable,
        source_object_id: str | None = None,
    ) -> PublishResult:
        policy = self.spec.write_policy
        if not isinstance(policy, ReplaceReferenceTables):
            raise TypeError(f"Dataset {self.spec.dataset_name} is not configured for reference-table replacement")

        source_date = str(raw_object.identity_key.get("source_date", "unknown"))
        soid = source_object_id or self.source_object_id(
            source_system=source_system,
            endpoint=endpoint,
            source_url=raw_object.version.source_url,
        )

        metadata = build_source_object_metadata(
            raw_object,
            source_system,
            endpoint,
            source_market_date=source_market_date,
            snapshot_ts=None,
        )
        metadata["source_object_id"] = soid

        from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode

        metrics: list[DuckLakeWriteMetrics] = []

        with self.session.transaction():
            self.provenance.record_source_object(metadata, table=provenance_table)
            self.provenance.mark_parsed(soid, table=provenance_table)

            for archive_name, table, arrow_table, source_name in prepared_tables:
                write_metrics = self.raw_tables.write_prepared_source(
                    arrow_table,
                    source_name=source_name,
                    table=table,
                    mode=DuckLakeWriterMode.REPLACE_TABLE,
                )
                logger.debug(
                    "Published reference table=%s archive_member=%s rows=%d replaced_rows=%d",
                    table.value,
                    archive_name,
                    arrow_table.num_rows,
                    write_metrics.replaced_rows,
                )
                metrics.append(write_metrics)

            self.provenance.mark_ingested(soid, table=provenance_table)

        return PublishResult(
            success=True,
            source_date=source_date,
            write_metrics=tuple(metrics),
        )

    ##############################
    # Error Handling
    ##############################

    def fail_source_object(
        self,
        *,
        source_object_id: str,
        table: RawDuckLakeProvenanceTable,
        reason: str,
    ) -> None:
        self.provenance.mark_failed(source_object_id, table=table, reason=reason)
