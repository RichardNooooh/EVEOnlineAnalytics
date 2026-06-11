from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import date, datetime

    import pyarrow as pa

    from eve_ingest.ducklake.raw_tables import RawDuckLakeTable
    from eve_ingest.ducklake.session import SqlSource
    from eve_ingest.raw_objects.models import AcquiredRawObject


@dataclass(frozen=True)
class PreparedSnapshotSqlSource:
    """A snapshot source ready for publication."""

    raw_object: AcquiredRawObject
    source_system: str
    endpoint: str
    source_market_date: date
    snapshot_ts: datetime
    table: RawDuckLakeTable
    sql_source: SqlSource
    log_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedAuthoritativeArrowSource:
    """An authoritative partition source (e.g. market history) ready for publication."""

    raw_object: AcquiredRawObject
    source_system: str
    endpoint: str
    source_market_date: date
    table: RawDuckLakeTable
    arrow_table: pa.Table
    log_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedReferenceTableSource:
    """One reference table replacement ready for publication."""

    raw_object: AcquiredRawObject | None
    source_system: str
    endpoint: str
    table: RawDuckLakeTable
    arrow_table: pa.Table
    log_context: dict[str, Any] = field(default_factory=dict)
