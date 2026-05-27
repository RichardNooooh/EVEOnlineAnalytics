from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping, TypeAlias

IdentityScalar: TypeAlias = str | int | float | bool | None
IdentityKey: TypeAlias = Mapping[str, IdentityScalar]


class UpdateMode(StrEnum):
    SNAPSHOT = "snapshot"
    MUTABLE = "mutable"


class RawObjectStatus(StrEnum):
    HIT = "hit"
    STORED = "stored"


class ReadOutcome(StrEnum):
    NOT_MODIFIED = "not_modified"
    DOWNLOADED = "downloaded"


@dataclass(frozen=True)
class RawObjectRequest:
    """Description of one raw object to acquire.

    Example:
        ```python
        request = RawObjectRequest(
            dataset_name="market-history",
            source_url="https://data.everef.net/market-history/2026-01-01.csv.bz2",
            update_mode="mutable",
            identity_key={"source_date": "2026-01-01"},
        )
        ```
    """

    dataset_name: str
    source_url: str
    update_mode: UpdateMode | str
    identity_key: IdentityKey | None = None
    source_name: str | None = None
    source_path: str | None = None


@dataclass(frozen=True)
class RawObject:
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
class ClientReadResult:
    outcome: ReadOutcome
    fetched_at: datetime
    etag: str | None = None
    last_modified: str | None = None
    content_length: int | None = None
    temp_path: str | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class RawObjectResult:
    """Current cached version for one raw object.

    Example:
        ```python
        result = cache.get(...)
        if result.changed:
            print("downloaded", result.path)
        ```
    """

    status: RawObjectStatus
    raw_object: RawObject
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
        """Return true when this call downloaded and stored a new version.

        Example:
            ```python
            if not result.changed:
                return
            ```
        """

        return self.status is RawObjectStatus.STORED
