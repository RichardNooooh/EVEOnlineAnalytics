from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from ingest.cache.ledger.mappers import row_to_raw_object, row_to_raw_object_version
from ingest.cache.ledger._db import _fetchall, _fetchone
from ingest.cache.ledger.schema import raw_object_versions, raw_objects
from ingest.cache.ledger.types import RawObjectEntry, RawObjectRef, RawObjectVersion


class RawObjectReader:
    def __init__(self, con: Connection) -> None:
        self._con = con

    def load_raw_object(
        self,
        *,
        ref: RawObjectRef,
    ) -> RawObjectEntry | None:
        row = _fetchone(
            self._con,
            select(raw_objects).where(
                raw_objects.c.source_name == ref.source_name,
                raw_objects.c.dataset_name == ref.dataset_name,
                raw_objects.c.identity_hash == ref.identity_hash,
            ),
        )
        if row is None:
            return None
        return row_to_raw_object(row)

    def load_raw_objects(
        self,
        *,
        group_key: tuple[str, str],
        identity_hashes: list[str],
    ) -> dict[str, RawObjectEntry]:
        if not identity_hashes:
            return {}
        source_name, dataset_name = group_key
        rows = _fetchall(
            self._con,
            select(raw_objects).where(
                raw_objects.c.source_name == source_name,
                raw_objects.c.dataset_name == dataset_name,
                raw_objects.c.identity_hash.in_(identity_hashes),
            ),
        )
        return {raw_object.ref.identity_hash: raw_object for raw_object in (row_to_raw_object(row) for row in rows)}

    def load_latest_version(self, raw_object_id: str) -> RawObjectVersion | None:
        row = _fetchone(
            self._con,
            select(raw_object_versions)
            .where(raw_object_versions.c.raw_object_id == raw_object_id)
            .order_by(raw_object_versions.c.version_number.desc())
            .limit(1),
        )
        if row is None:
            return None
        return row_to_raw_object_version(row)

    def load_latest_versions(self, raw_object_ids: list[str]) -> dict[str, RawObjectVersion]:
        if not raw_object_ids:
            return {}
        subq = (
            select(
                raw_object_versions,
                func.row_number()
                .over(
                    partition_by=raw_object_versions.c.raw_object_id,
                    order_by=[
                        raw_object_versions.c.version_number.desc(),
                    ],
                )
                .label("rn"),
            )
            .where(raw_object_versions.c.raw_object_id.in_(raw_object_ids))
            .subquery()
        )
        rows = _fetchall(self._con, select(subq).where(subq.c.rn == 1))
        return {version.raw_object_id: version for version in (row_to_raw_object_version(row) for row in rows)}
