from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from ingest.cache.helpers import merge_revalidation
from ingest.cache.ledger.mappers import (
    raw_object_seen_values,
    raw_object_values,
    raw_object_version_values,
    row_to_raw_object_version,
)
from ingest.cache.ledger._db import _execute, _fetchall
from ingest.cache.ledger.reader import RawObjectReader
from ingest.cache.ledger.schema import raw_object_versions, raw_objects
from ingest.cache.ledger.types import RotateVersionResult
from ingest.cache.client_types import RevalidationMetadata
from ingest.cache.ledger.types import RawObjectEntry, RawObjectRef, RawObjectVersion


class RawObjectWriter:
    def __init__(self, con: Connection) -> None:
        self._con = con

    def touch_raw_object(
        self,
        *,
        ref: RawObjectRef,
        checked_at: datetime,
        revalidation: RevalidationMetadata | None = None,
    ) -> RawObjectEntry:
        existing = RawObjectReader(self._con).load_raw_object(ref=ref)
        revalidation = revalidation or RevalidationMetadata()
        if existing is None:
            raw_object = RawObjectEntry(
                id=uuid4().hex,
                ref=ref,
                created_at=checked_at,
                last_checked_at=checked_at,
                revalidation=revalidation,
            )
            _execute(self._con, raw_objects.insert().values(**raw_object_values(raw_object)))
            return raw_object

        updated = replace(
            existing,
            last_checked_at=checked_at,
            revalidation=merge_revalidation(existing.revalidation, revalidation),
        )
        _execute(
            self._con,
            update(raw_objects).where(raw_objects.c.id == existing.id).values(**raw_object_seen_values(updated)),
        )
        return updated

    def _list_versions(self, raw_object_id: str) -> list[RawObjectVersion]:
        rows = _fetchall(
            self._con, select(raw_object_versions).where(raw_object_versions.c.raw_object_id == raw_object_id)
        )
        return [row_to_raw_object_version(row) for row in rows]

    def rotate_version(
        self,
        *,
        ref: RawObjectRef,
        source_url: str,
        fetched_at: datetime,
        revalidation: RevalidationMetadata,
        sha256: str,
        local_path: str,
        storage_encoding: str,
    ) -> RotateVersionResult:
        raw_object = self.touch_raw_object(
            ref=ref,
            checked_at=fetched_at,
            revalidation=revalidation,
        )
        stale_versions = self._list_versions(raw_object.id)
        max_version = max((v.version_number for v in stale_versions), default=0)
        version = RawObjectVersion(
            id=uuid4().hex,
            raw_object_id=raw_object.id,
            source_url=source_url,
            fetched_at=fetched_at,
            revalidation=revalidation,
            sha256=sha256,
            local_path=local_path,
            storage_encoding=storage_encoding,
            version_number=max_version + 1,
        )
        _execute(self._con, raw_object_versions.insert().values(**raw_object_version_values(version)))
        return RotateVersionResult(
            raw_object=replace(
                raw_object,
                last_checked_at=fetched_at,
                revalidation=revalidation,
            ),
            version=version,
            stale_versions=stale_versions,
        )
