"""Public types for the raw object cache.

Types here are the public API surface for ``Cache`` callers.
Types that are internal implementation details live in separate modules:

- ``client_types.py`` — HTTP read result types (``ReadStatus``, ``ReadResult``, etc.)
- ``ledger/types.py`` — ledger record types (``RawObjectEntry``, ``RawObjectVersion``, etc.)
- ``plans.py`` — fetch plan types (``BaseFetchPlan``, ``ResolvedFetchPlan``, etc.)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ingest.cache.primitives import IdentityKey, IdentityScalar, UpdateMode
from ingest.cache.ledger.types import RawObjectEntry, RawObjectVersion


class CacheResultStatus(StrEnum):
    """Result of cache lookup for one object.

    `HIT` means cache reused existing local version. `STORED` means cache fetched
    and recorded new local version.
    """

    HIT = "hit"
    STORED = "stored"


class GetMode(StrEnum):
    """Filter mode for ``Cache.get_many()``.

    ``ALL`` returns every result. ``CHANGED`` (default) returns only newly
    downloaded versions. ``UNPUBLISHED`` returns versions without a publication
    marker.
    """

    ALL = "all"
    CHANGED = "changed"
    UNPUBLISHED = "unpublished"


@dataclass(frozen=True)
class CacheObject:
    """Per-object description of one raw object to acquire.

    Example:
        ```python
        object_ref = CacheObject(
            source_url="https://data.everef.net/market-history/2026-01-01.csv.bz2",
            identity_key={"source_date": "2026-01-01"},
        )
        ```
    """

    source_url: str
    identity_key: IdentityKey | None = None
    source_path: str | None = None


@dataclass(frozen=True)
class CacheResult:
    """Current cached version for one raw object.

    Example:
        ```python
        result = cache.get(CacheObject(source_url=url))
        if result.changed:
            print("downloaded", result.path)
        ```
    """

    status: CacheResultStatus
    raw_object: RawObjectEntry
    version: RawObjectVersion

    @property
    def path(self) -> str:
        """Return local filesystem path for this cached version."""

        return self.version.local_path

    @property
    def identity_key(self) -> IdentityKey:
        """Return logical identity used for cache lookup.

        Example:
            ```python
            assert result.identity_key["source_date"] == "2026-01-01"
            ```
        """

        return self.raw_object.identity_key

    @property
    def update_mode(self) -> UpdateMode:
        """Return update mode used by this raw object."""

        return self.raw_object.update_mode

    @property
    def changed(self) -> bool:
        """Return true when this call downloaded and stored new version."""

        return self.status is CacheResultStatus.STORED
