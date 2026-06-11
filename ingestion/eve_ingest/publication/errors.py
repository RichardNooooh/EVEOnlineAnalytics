from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable


class SnapshotScopePublishError(RuntimeError):
    def __init__(
        self,
        *,
        source_ref_id: str,
        provenance_table: RawDuckLakeProvenanceTable,
        metadata: dict,
        source_date: str,
        reason: str = "see log for details",
    ) -> None:
        super().__init__(f"Snapshot publication failed source_date={source_date} source_ref_id={source_ref_id}")
        self.source_ref_id = source_ref_id
        self.provenance_table = provenance_table
        self.metadata = metadata
        self.source_date = source_date
        self.reason = reason
