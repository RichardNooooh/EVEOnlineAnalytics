"""Core data models for the raw object cache.

Defines types for cache policy, fetch results, ledger records, and fetch plans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Mapping, TypeAlias

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
class RevalidationMetadata:
    """HTTP revalidation metadata used for conditional requests.

    Carries ``ETag``, ``Last-Modified``, and ``Content-Length`` observed from the
    origin so that mutable objects can be re-fetched with ``If-None-Match`` or
    ``If-Modified-Since`` headers.
    """

    etag: str | None = None
    last_modified: str | None = None
    content_length: int | None = None

    def request_headers(self) -> dict[str, str]:
        """Return conditional request headers for revalidation.

        Prefers ``If-None-Match`` when ``etag`` is present, otherwise falls back
        to ``If-Modified-Since``. Returns an empty dict when neither is set.

        Returns:
            Dict with zero or one conditional header.
        """
        if self.etag:
            return {"If-None-Match": self.etag}
        if self.last_modified:
            return {"If-Modified-Since": self.last_modified}
        return {}


@dataclass(frozen=True)
class PublicationContext:
    """Publication marker for a cached raw object version.

    Bundles scope, run id, and timestamp so the same context can be reused across
    many `mark_published` calls.
    """

    published_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    publication_scope: str | None = None
    publisher_run_id: str | None = None


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
    `MODIFIED` means client wrote fresh content to temporary storage.
    """

    NOT_MODIFIED = "not_modified"
    MODIFIED = "modified"


@dataclass(frozen=True)
class RawObjectRef:
    """Stable composite key for one logical raw object.

    Combines the source, dataset, and hashed identity into a unique reference
    used for ledger lookups.
    """

    source_name: str
    dataset_name: str
    identity_hash: str

    @property
    def group_key(self) -> tuple[str, str]:
        """Return (source_name, dataset_name) for batching queries."""
        return (self.source_name, self.dataset_name)


@dataclass(frozen=True)
class RawObjectDefinition:
    """Immutable description of a raw object used during fetch planning.

    Bundles the composite key, logical identity, and cache policy so that the
    ledger can resolve whether an object exists and which update mode applies.
    """

    ref: RawObjectRef
    identity_key: IdentityKey
    update_mode: UpdateMode


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
    revalidation: RevalidationMetadata = RevalidationMetadata()

    @property
    def ref(self) -> RawObjectRef:
        """Return composite key for this raw object."""
        return RawObjectRef(
            source_name=self.source_name,
            dataset_name=self.dataset_name,
            identity_hash=self.identity_hash,
        )

    @property
    def definition(self) -> RawObjectDefinition:
        """Return immutable definition for this raw object."""
        return RawObjectDefinition(
            ref=self.ref,
            identity_key=self.identity_key,
            update_mode=self.update_mode,
        )


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
    revalidation: RevalidationMetadata
    sha256: str
    local_path: str
    storage_encoding: str


@dataclass(frozen=True)
class NotModifiedResult:
    """Result when origin reports 304 Not Modified."""

    outcome: Literal[FetchOutcome.NOT_MODIFIED]
    fetched_at: datetime
    revalidation: RevalidationMetadata = RevalidationMetadata()


@dataclass(frozen=True)
class ModifiedResult:
    """Result when origin returns new content."""

    outcome: Literal[FetchOutcome.MODIFIED]
    fetched_at: datetime
    temp_path: str
    sha256: str
    revalidation: RevalidationMetadata = RevalidationMetadata()


FetchResult: TypeAlias = NotModifiedResult | ModifiedResult


@dataclass(frozen=True)
class BaseFetchPlan:
    """Immutable fetch plan built from a ``CacheObject`` before ledger resolution.

    Carries everything needed to perform an HTTP read: URL, identity, policy,
    and the temporary path where the response body should be streamed.
    """

    source_name: str
    dataset_name: str
    source_url: str
    source_relative_path: str
    update_mode: UpdateMode
    identity_key: IdentityKey
    identity_hash: str
    temp_path: str

    @property
    def ref(self) -> RawObjectRef:
        """Return composite key for this plan."""
        return RawObjectRef(
            source_name=self.source_name,
            dataset_name=self.dataset_name,
            identity_hash=self.identity_hash,
        )

    @property
    def definition(self) -> RawObjectDefinition:
        """Return immutable definition for this plan."""
        return RawObjectDefinition(
            ref=self.ref,
            identity_key=self.identity_key,
            update_mode=self.update_mode,
        )


@dataclass(frozen=True)
class ResolvedFetchPlan(BaseFetchPlan):
    """Fetch plan enriched with ledger state.

    ``raw_object`` is ``None`` when the object has never been seen.
    ``current_version`` is ``None`` when no version has been stored yet.
    """

    raw_object: RawObjectEntry | None
    current_version: RawObjectVersion | None
