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
    status: RawObjectStatus
    raw_object: RawObject
    version: RawObjectVersion

    @property
    def path(self) -> str:
        return self.version.local_path

    @property
    def identity_key(self) -> IdentityKey:
        return self.raw_object.identity_key

    @property
    def update_mode(self) -> UpdateMode:
        return self.raw_object.update_mode

    @property
    def changed(self) -> bool:
        return self.status is RawObjectStatus.STORED
