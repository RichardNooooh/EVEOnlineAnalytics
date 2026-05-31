from __future__ import annotations

from dataclasses import dataclass

from eve_ingest.raw_objects.ledger.models import RawObjectRef


@dataclass(frozen=True)
class FetchPlan:
    ref: RawObjectRef
    source_url: str
    source_relative_path: str
    temp_path: str
