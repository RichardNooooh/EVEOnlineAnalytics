from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from ingest.cache.models import RawObjectEntry, RawObjectVersion, UpdateMode


class InMemoryRawObjectLedger:
    def __init__(self) -> None:
        self._raw_objects_by_key: dict[tuple[str, str, str], RawObjectEntry] = {}
        self._versions_by_object_id: dict[str, list[RawObjectVersion]] = {}
        self._publications: set[tuple[str, str, str, str]] = set()
        self.load_raw_objects_calls = 0
        self.load_latest_versions_calls = 0
        self.filter_published_calls = 0

    def close(self) -> None:
        return None

    @contextmanager
    def transaction(self) -> Iterator[InMemoryRawObjectLedgerTx]:
        yield InMemoryRawObjectLedgerTx(self)


class InMemoryRawObjectLedgerTx:
    def __init__(self, ledger: InMemoryRawObjectLedger) -> None:
        self._ledger = ledger

    def load_raw_object(
        self,
        *,
        source_name: str,
        dataset_name: str,
        identity_hash: str,
    ) -> RawObjectEntry | None:
        return self._ledger._raw_objects_by_key.get(
            (source_name, dataset_name, identity_hash)
        )

    def load_raw_objects(
        self,
        *,
        source_name: str,
        dataset_name: str,
        identity_hashes: list[str],
    ) -> dict[str, RawObjectEntry]:
        self._ledger.load_raw_objects_calls += 1
        return {
            identity_hash: raw_object
            for identity_hash in identity_hashes
            if (
                raw_object := self._ledger._raw_objects_by_key.get(
                    (source_name, dataset_name, identity_hash)
                )
            )
            is not None
        }

    def load_latest_version(self, raw_object_id: str) -> RawObjectVersion | None:
        versions = self._ledger._versions_by_object_id.get(raw_object_id, [])
        return versions[0] if versions else None

    def load_latest_versions(
        self, raw_object_ids: list[str]
    ) -> dict[str, RawObjectVersion]:
        self._ledger.load_latest_versions_calls += 1
        return {
            raw_object_id: versions[0]
            for raw_object_id in raw_object_ids
            if (versions := self._ledger._versions_by_object_id.get(raw_object_id))
        }

    def touch_raw_object(
        self,
        *,
        source_name: str,
        dataset_name: str,
        identity_key: Mapping[str, Any],
        identity_hash: str,
        update_mode: UpdateMode,
        checked_at: datetime,
        current_version: RawObjectVersion | None,
    ) -> RawObjectEntry:
        key = (source_name, dataset_name, identity_hash)
        existing = self._ledger._raw_objects_by_key.get(key)
        if existing is None:
            raw_object = RawObjectEntry(
                id=uuid4().hex,
                source_name=source_name,
                dataset_name=dataset_name,
                identity_key=dict(identity_key),
                identity_hash=identity_hash,
                update_mode=update_mode,
                created_at=checked_at,
                last_checked_at=checked_at,
                last_seen_etag=current_version.etag if current_version else None,
                last_seen_last_modified=current_version.last_modified
                if current_version
                else None,
                last_seen_content_length=current_version.content_length
                if current_version
                else None,
            )
            self._ledger._raw_objects_by_key[key] = raw_object
            return raw_object

        updated = replace(
            existing,
            last_checked_at=checked_at,
            last_seen_etag=(
                current_version.etag if current_version else existing.last_seen_etag
            ),
            last_seen_last_modified=(
                current_version.last_modified
                if current_version
                else existing.last_seen_last_modified
            ),
            last_seen_content_length=(
                current_version.content_length
                if current_version
                else existing.last_seen_content_length
            ),
        )
        self._ledger._raw_objects_by_key[key] = updated
        return updated

    def insert_version(self, version: RawObjectVersion) -> None:
        versions = self._ledger._versions_by_object_id.setdefault(
            version.raw_object_id, []
        )
        versions.append(version)
        versions.sort(key=lambda item: (item.fetched_at, item.id), reverse=True)

        for key, raw_object in self._ledger._raw_objects_by_key.items():
            if raw_object.id == version.raw_object_id:
                self._ledger._raw_objects_by_key[key] = replace(
                    raw_object,
                    last_seen_etag=version.etag,
                    last_seen_last_modified=version.last_modified,
                    last_seen_content_length=version.content_length,
                )
                break

    def list_versions(self, raw_object_id: str) -> list[RawObjectVersion]:
        return list(self._ledger._versions_by_object_id.get(raw_object_id, []))

    def delete_versions(self, version_ids: list[str]) -> None:
        ids = set(version_ids)
        for raw_object_id, versions in self._ledger._versions_by_object_id.items():
            self._ledger._versions_by_object_id[raw_object_id] = [
                version for version in versions if version.id not in ids
            ]

    def mark_published(
        self,
        *,
        source_name: str,
        dataset_name: str,
        identity_hash: str,
        sha256: str,
        version_id: str,
        published_at: datetime,
        publication_scope: str | None,
        publisher_run_id: str | None,
    ) -> None:
        self._ledger._publications.add(
            (source_name, dataset_name, identity_hash, sha256)
        )

    def is_published(
        self,
        *,
        source_name: str,
        dataset_name: str,
        identity_hash: str,
        sha256: str,
    ) -> bool:
        return (
            source_name,
            dataset_name,
            identity_hash,
            sha256,
        ) in self._ledger._publications

    def filter_published(
        self,
        *,
        source_name: str,
        dataset_name: str,
        versions: list[tuple[str, str]],
    ) -> set[tuple[str, str]]:
        self._ledger.filter_published_calls += 1
        return {
            (identity_hash, sha256)
            for identity_hash, sha256 in versions
            if (source_name, dataset_name, identity_hash, sha256)
            in self._ledger._publications
        }
