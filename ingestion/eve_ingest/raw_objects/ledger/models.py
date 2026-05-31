from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from eve_ingest.raw_objects.http_models import RevalidationMetadata
from eve_ingest.raw_objects.primitives import IdentityKey, UpdateMode


@dataclass(frozen=True)
class RawObjectRef:
    """Stable composite key for one logical raw object.

    Combines the source, dataset, and hashed identity into a unique reference
    used for ledger lookups. Also carries the logical identity key and cache
    policy so no companion ``RawObjectDefinition`` is needed.
    """

    source_name: str
    dataset_name: str
    identity_hash: str
    identity_key: IdentityKey
    update_mode: UpdateMode

    @property
    def group_key(self) -> tuple[str, str]:
        """Return (source_name, dataset_name) for batching queries."""
        return (self.source_name, self.dataset_name)


@dataclass(frozen=True)
class RawObjectEntry:
    """Ledger record for logical raw object identity.

    One entry tracks stable object identity, cache policy, and last-observed remote
    metadata across version fetches. ``identity_key`` and ``update_mode`` live on
    ``ref``.
    """

    id: str
    ref: RawObjectRef
    created_at: datetime
    last_checked_at: datetime | None = None
    revalidation: RevalidationMetadata = RevalidationMetadata()


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
    version_number: int


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
class RotateVersionResult:
    raw_object: RawObjectEntry
    version: RawObjectVersion
    stale_versions: list[RawObjectVersion]


@dataclass(frozen=True)
class CurrentRawObjectState:
    raw_object: RawObjectEntry
    current_version: RawObjectVersion
