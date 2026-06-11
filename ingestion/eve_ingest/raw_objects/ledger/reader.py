from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from eve_ingest.raw_objects.ledger._db import _fetchall, _fetchone
from eve_ingest.raw_objects.ledger.models import CurrentRawObjectState, RawObjectEntry, RawObjectRef, RawObjectVersion
from eve_ingest.raw_objects.ledger.row_mappers import row_to_raw_object, row_to_raw_object_version
from eve_ingest.raw_objects.ledger.schema import raw_object_versions, raw_objects

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection


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

    def list_all_version_paths(self) -> list[str]:
        """Return all ``local_path`` values recorded in the ledger."""
        rows = _fetchall(self._con, select(raw_object_versions.c.local_path))
        return [row["local_path"] for row in rows]

    def load_current_states(
        self,
        *,
        refs: list[RawObjectRef],
    ) -> dict[str, CurrentRawObjectState | None]:
        if not refs:
            return {}

        groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        for ref in refs:
            groups[ref.group_key].append(ref.identity_hash)

        raw_objects: dict[str, RawObjectEntry] = {}
        for (source_name, dataset_name), hashes in groups.items():
            raw_objects.update(
                self.load_raw_objects(
                    group_key=(source_name, dataset_name),
                    identity_hashes=hashes,
                )
            )

        raw_object_ids = [ro.id for ro in raw_objects.values()]
        latest_versions = self.load_latest_versions(raw_object_ids) if raw_object_ids else {}

        states: dict[str, CurrentRawObjectState | None] = {}
        for ref in refs:
            raw_object = raw_objects.get(ref.identity_hash)
            if raw_object is None:
                states[ref.identity_hash] = None
            else:
                current_version = latest_versions.get(raw_object.id)
                if current_version is None:
                    raise RuntimeError(f"Ledger corruption: raw_object {raw_object.id} exists but has no versions")
                states[ref.identity_hash] = CurrentRawObjectState(
                    raw_object=raw_object,
                    current_version=current_version,
                )
        return states
