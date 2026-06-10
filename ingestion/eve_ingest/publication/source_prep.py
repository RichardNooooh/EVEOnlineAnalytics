from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime

import pyarrow as pa

from eve_ingest.ducklake.raw_tables import compute_source_ref_id
from eve_ingest.ducklake.session import DuckLakeSession, SqlSource
from eve_ingest.raw_objects.models import AcquiredRawObject
from eve_ingest.ducklake.provenance_metadata import build_source_object_metadata


@dataclass
class SourcePreparationContext:
    """SQL quoting, temp views, Arrow registration, and source metadata building.

    Wraps a DuckLakeSession for the temp view / Arrow operations. Source modules
    use this to prepare data for publication without touching provenance or raw
    table lifecycle.
    """

    session: DuckLakeSession

    def source_ref_id(
        self,
        *,
        source_system: str,
        endpoint: str,
        source_url: str,
    ) -> str:
        return compute_source_ref_id(source_system, endpoint, source_url)

    def quote_sql_string(self, value: str) -> str:
        return self.session.quote_sql_string(value)

    @contextmanager
    def prepare_sql_source(self, sql_source: SqlSource) -> Iterator[str]:
        with self.session.prepare_sql_source(sql_source) as source_name:
            yield source_name

    @contextmanager
    def prepare_arrow_source(self, arrow_table: pa.Table) -> Iterator[str]:
        with self.session.prepare_arrow_source(arrow_table) as source_name:
            yield source_name

    def build_source_object_metadata(
        self,
        raw_object: AcquiredRawObject,
        source_system: str,
        endpoint: str,
        *,
        source_ref_id: str,
        source_market_date: date | None = None,
        snapshot_ts: datetime | None = None,
    ) -> dict:
        return build_source_object_metadata(
            raw_object,
            source_system,
            endpoint,
            source_ref_id=source_ref_id,
            source_market_date=source_market_date,
            snapshot_ts=snapshot_ts,
        )
