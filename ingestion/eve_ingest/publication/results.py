from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eve_ingest.ducklake.raw_tables import DuckLakeWriteMetrics

##############################
# Publication Results
##############################


@dataclass(frozen=True)
class PublishResult:
    success: bool
    source_date: str | None
    write_metrics: tuple[DuckLakeWriteMetrics, ...] = ()


##############################
# Published Object
##############################


@dataclass(frozen=True)
class PublishedObject:
    source_ref_id: str
    source_date: str | None
    write_metrics: tuple[DuckLakeWriteMetrics, ...]
