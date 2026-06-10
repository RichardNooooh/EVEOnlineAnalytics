from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable
from eve_ingest.publication.prepared_source import (
    PreparedAuthoritativeArrowSource,
    PreparedReferenceTableSource,
    PreparedSnapshotSqlSource,
)
from eve_ingest.publication.results import PublishResult
from eve_ingest.publication.service import PublicationService
from eve_ingest.publication.source_prep import SourcePreparationContext
from eve_ingest.raw_objects.models import CacheResult

logger = logging.getLogger(__name__)

##############################
# PublishContext (facade)
##############################


@dataclass
class PublishContext:
    """Thin facade over SourcePreparationContext + PublicationService.

    Source modules continue to receive a single ``ctx`` argument. The facade
    preserves the familiar method names while delegating preparation to
    ``SourcePreparationContext`` and lifecycle management to ``PublicationService``.
    """

    spec: object
    prep_ctx: SourcePreparationContext
    service: PublicationService
    publication_scope: str

    def source_ref_id(
        self,
        *,
        source_system: str,
        endpoint: str,
        source_url: str,
    ) -> str:
        return self.prep_ctx.source_ref_id(source_system=source_system, endpoint=endpoint, source_url=source_url)

    def quote_sql_string(self, value: str) -> str:
        return self.prep_ctx.quote_sql_string(value)

    ##############################
    # Snapshot SQL Publication
    ##############################

    def append_snapshot_sql(
        self,
        prepared: PreparedSnapshotSqlSource,
        *,
        source_ref_id: str | None = None,
    ) -> PublishResult:
        return self.service.append_snapshot(prepared, ctx=self.prep_ctx, source_ref_id=source_ref_id)

    ##############################
    # Insert Missing Keys Publication
    ##############################

    def insert_missing_keys_arrow(
        self,
        prepared: PreparedAuthoritativeArrowSource,
        *,
        source_ref_id: str | None = None,
    ) -> PublishResult:
        return self.service.insert_missing_keys(prepared, ctx=self.prep_ctx, source_ref_id=source_ref_id)

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
        prepared_tables: Sequence[PreparedReferenceTableSource],
        provenance_table: RawDuckLakeProvenanceTable,
        source_ref_id: str | None = None,
    ) -> PublishResult:
        return self.service.replace_tables(
            raw_object=raw_object,
            source_system=source_system,
            endpoint=endpoint,
            source_market_date=source_market_date,
            prepared_tables=list(prepared_tables),
            provenance_table=provenance_table,
            source_ref_id=source_ref_id,
            ctx=self.prep_ctx,
        )

    ##############################
    # Error Handling
    ##############################

    def fail_source_object(
        self,
        *,
        source_ref_id: str,
        table: RawDuckLakeProvenanceTable,
        reason: str,
    ) -> None:
        self.service.mark_failed(source_ref_id, table=table, reason=reason)
