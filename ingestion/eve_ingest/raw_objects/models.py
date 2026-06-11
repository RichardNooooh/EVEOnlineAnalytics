"""Public types for the raw object store.

Types here are the public API surface for raw object store callers.
Types that are internal implementation details live in separate modules:

- ``client_types.py`` — HTTP read result types (``ReadStatus``, ``ReadResult``, etc.)
- ``ledger/types.py`` — ledger record types (``RawObjectEntry``, ``RawObjectVersion``, etc.)
- ``plans.py`` — fetch plan type (``FetchPlan``)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eve_ingest.raw_objects.ledger.models import RawObjectEntry, RawObjectVersion
    from eve_ingest.raw_objects.primitives import IdentityKey, UpdateMode


class AcquisitionStatus(StrEnum):
    """Result of acquisition for one raw object.

    `HIT` means store reused existing local version. `STORED` means store fetched
    and recorded new local version.
    """

    HIT = "hit"
    STORED = "stored"


class AcquisitionMode(StrEnum):
    """Filter mode for ``RawObjectStore.get_many()``.

    ``ALL`` returns every result. ``CHANGED`` (default) returns only newly
    downloaded versions.
    """

    ALL = "all"
    CHANGED = "changed"


@dataclass(frozen=True)
class RawObjectRequest:
    """Per-object description of one raw object to acquire.

    Example:
        ```python
        object_ref = RawObjectRequest(
            source_url="https://data.everef.net/market-history/2026-01-01.csv.bz2",
            identity_key={"source_date": "2026-01-01"},
        )
        ```
    """

    source_url: str
    identity_key: IdentityKey
    source_path: str | None = None


@dataclass(frozen=True)
class AcquiredRawObject:
    """Current acquired version for one raw object.

    Example:
        ```python
        result = store.get(RawObjectRequest(source_url=url, identity_key={"source": url}))
        if result.changed:
            print("downloaded", result.path)
        ```
    """

    status: AcquisitionStatus
    raw_object: RawObjectEntry
    version: RawObjectVersion

    @property
    def path(self) -> str:
        """Return local filesystem path for this acquired version."""

        return self.version.local_path

    @property
    def identity_key(self) -> IdentityKey:
        """Return logical identity used for raw object store lookup.

        Example:
            ```python
            assert result.identity_key["source_date"] == "2026-01-01"
            ```
        """

        return self.raw_object.ref.identity_key

    @property
    def update_mode(self) -> UpdateMode:
        """Return update mode used by this raw object."""

        return self.raw_object.ref.update_mode

    @property
    def changed(self) -> bool:
        """Return true when this call downloaded and stored new version."""

        return self.status is AcquisitionStatus.STORED
