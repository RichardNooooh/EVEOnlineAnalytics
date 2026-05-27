from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping, TypeAlias

IdentityScalar: TypeAlias = str | int | float | bool | None
IdentityKey: TypeAlias = Mapping[str, IdentityScalar]


class UpdateMode(StrEnum):
    """Cache behavior for how source object changes over time.

    `SNAPSHOT` means URL points at immutable content, so cache can trust local file
    once stored. `MUTABLE` means URL may change in place, so cache must re-check
    origin with conditional requests.
    """

    SNAPSHOT = "snapshot"
    MUTABLE = "mutable"


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
        """Return local filesystem path for this cached version.

        Example:
            ```python
            process_file(result.path)
            ```
        """

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
        """Return update mode used by this raw object.

        Example:
            ```python
            if result.update_mode is UpdateMode.MUTABLE:
                ...
            ```
        """

        return self.raw_object.update_mode

    @property
    def changed(self) -> bool:
        """Return true when this call downloaded and stored new version.

        Example:
            ```python
            if not result.changed:
                return
            ```
        """

        return self.status is CacheResultStatus.STORED


class CacheResultStatus(StrEnum):
    """Result of cache lookup for one object.

    `HIT` means cache reused existing local version. `STORED` means cache fetched
    and recorded new local version.
    """

    HIT = "hit"
    STORED = "stored"


class FetchOutcome(StrEnum):
    """Low-level HTTP read outcome from cache client.

    `NOT_MODIFIED` means origin confirmed existing cached version still current.
    `DOWNLOADED` means client wrote fresh content to temporary storage.
    """

    NOT_MODIFIED = "not_modified"
    DOWNLOADED = "downloaded"


@dataclass(frozen=True)
class RawObjectEntry:
    """Ledger record for logical raw object identity.

    One entry tracks stable object identity, cache policy, and last-observed remote
    metadata across version fetches.
    """

    id: str
    source_name: str
    dataset_name: str
    identity_key: IdentityKey
    identity_hash: str
    update_mode: UpdateMode
    created_at: datetime
    last_checked_at: datetime | None = None
    last_seen_etag: str | None = None
    last_seen_last_modified: str | None = None
    last_seen_content_length: int | None = None


@dataclass(frozen=True)
class RawObjectVersion:
    """Ledger record for one concrete fetched version of raw object.

    Stores provenance, fetch metadata, checksum, and local filesystem path for one
    cached payload.
    """

    id: str
    raw_object_id: str
    source_url: str
    fetched_at: datetime
    etag: str | None
    last_modified: str | None
    content_length: int | None
    sha256: str
    local_path: str
    storage_encoding: str


@dataclass(frozen=True)
class FetchResult:
    """Result returned by cache client after reading source object.

    Carries HTTP freshness metadata for not-modified checks or downloaded file
    metadata for newly fetched content.
    """

    outcome: FetchOutcome
    fetched_at: datetime
    etag: str | None = None
    last_modified: str | None = None
    content_length: int | None = None
    temp_path: str | None = None
    sha256: str | None = None
