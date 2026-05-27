from dataclasses import dataclass

from ingest.cache.models import RawObjectEntry, RawObjectVersion


@dataclass(frozen=True)
class ReplaceCurrentVersionResult:
    raw_object: RawObjectEntry
    version: RawObjectVersion
    stale_versions: list[RawObjectVersion]
