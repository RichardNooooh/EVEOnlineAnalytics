from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from eve_ingest.raw_objects.helpers import merge_revalidation
from eve_ingest.raw_objects.ledger.row_mappers import (
    raw_object_seen_values,
    raw_object_values,
    raw_object_version_values,
    row_to_raw_object,
    row_to_raw_object_version,
)
from eve_ingest.raw_objects.ledger._db import _execute, _fetchall, _fetchone
from eve_ingest.raw_objects.ledger.reader import RawObjectReader
from eve_ingest.raw_objects.ledger.schema import raw_object_versions, raw_objects
from eve_ingest.raw_objects.ledger.models import RotateVersionResult
from eve_ingest.raw_objects.http_models import RevalidationMetadata
from eve_ingest.raw_objects.ledger.models import RawObjectEntry, RawObjectRef, RawObjectVersion


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
        if self._con.dialect.name == "postgresql":
            return self._touch_raw_object_postgresql(
                ref=ref,
                checked_at=checked_at,
                revalidation=revalidation,
            )

        return self._touch_raw_object_read_then_write(
            ref=ref,
            checked_at=checked_at,
            revalidation=revalidation,
        )

    def _touch_raw_object_read_then_write(
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

    def _touch_raw_object_postgresql(
        self,
        *,
        ref: RawObjectRef,
        checked_at: datetime,
        revalidation: RevalidationMetadata | None = None,
    ) -> RawObjectEntry:
        revalidation = revalidation or RevalidationMetadata()
        raw_object = RawObjectEntry(
            id=uuid4().hex,
            ref=ref,
            created_at=checked_at,
            last_checked_at=checked_at,
            revalidation=revalidation,
        )
        statement = pg_insert(raw_objects).values(**raw_object_values(raw_object))
        row = _fetchone(
            self._con,
            statement.on_conflict_do_update(
                index_elements=[
                    raw_objects.c.source_name,
                    raw_objects.c.dataset_name,
                    raw_objects.c.identity_hash,
                ],
                set_={
                    "last_checked_at": checked_at,
                    "etag": func.coalesce(statement.excluded.etag, raw_objects.c.etag),
                    "last_modified": func.coalesce(statement.excluded.last_modified, raw_objects.c.last_modified),
                    "content_length": func.coalesce(statement.excluded.content_length, raw_objects.c.content_length),
                },
            ).returning(raw_objects),
        )
        if row is None:
            raise RuntimeError("Could not upsert raw object")
        return row_to_raw_object(row)

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
        self._lock_raw_object(raw_object.id)
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

    def _lock_raw_object(self, raw_object_id: str) -> None:
        _fetchone(
            self._con,
            select(raw_objects.c.id).where(raw_objects.c.id == raw_object_id).with_for_update(),
        )
