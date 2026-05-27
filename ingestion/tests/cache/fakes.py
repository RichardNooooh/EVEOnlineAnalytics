from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from ingest.cache.client_types import RevalidationMetadata
from ingest.cache.helpers import merge_revalidation
from ingest.cache.ledger.runtime import LedgerTx
from ingest.cache.ledger.types import (
    PublicationContext,
    RawObjectEntry,
    RawObjectRef,
    RawObjectVersion,
    RotateVersionResult,
)
from ingest.cache.plans import (
    BaseFetchPlan,
    FetchPlan,
    ResolvedFetchPlan,
    UnresolvedFetchPlan,
)


class InMemoryRawObjectReader:
    def __init__(self, ledger: InMemoryRawObjectLedger) -> None:
        self._ledger = ledger

    def load_raw_object(
        self,
        *,
        ref: RawObjectRef,
    ) -> RawObjectEntry | None:
        return self._ledger._raw_objects_by_key.get(ref.group_key + (ref.identity_hash,))

    def load_raw_objects(
        self,
        *,
        group_key: tuple[str, str],
        identity_hashes: list[str],
    ) -> dict[str, RawObjectEntry]:
        result: dict[str, RawObjectEntry] = {}
        for identity_hash in identity_hashes:
            entry = self._ledger._raw_objects_by_key.get(group_key + (identity_hash,))
            if entry is not None:
                result[identity_hash] = entry
        return result

    def load_latest_versions(self, raw_object_ids: list[str]) -> dict[str, RawObjectVersion]:
        result: dict[str, RawObjectVersion] = {}
        for oid in raw_object_ids:
            versions = self._ledger._versions_by_object_id.get(oid, [])
            if versions:
                result[oid] = versions[0]
        return result


class InMemoryRawObjectWriter:
    def __init__(self, ledger: InMemoryRawObjectLedger) -> None:
        self._ledger = ledger

    def touch_raw_object(
        self,
        *,
        ref: RawObjectRef,
        checked_at: datetime,
        revalidation: RevalidationMetadata | None = None,
    ) -> RawObjectEntry:
        key = ref.group_key + (ref.identity_hash,)
        existing = self._ledger._raw_objects_by_key.get(key)
        revalidation = revalidation or RevalidationMetadata()
        if existing is None:
            raw_object = RawObjectEntry(
                id=uuid4().hex,
                ref=ref,
                created_at=checked_at,
                last_checked_at=checked_at,
                revalidation=revalidation,
            )
            self._ledger._raw_objects_by_key[key] = raw_object
            return raw_object

        updated = replace(
            existing,
            last_checked_at=checked_at,
            revalidation=merge_revalidation(existing.revalidation, revalidation),
        )
        self._ledger._raw_objects_by_key[key] = updated
        return updated

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
        stale_versions = list(self._ledger._versions_by_object_id.get(raw_object.id, []))
        version = RawObjectVersion(
            id=uuid4().hex,
            raw_object_id=raw_object.id,
            source_url=source_url,
            fetched_at=fetched_at,
            revalidation=revalidation,
            sha256=sha256,
            local_path=local_path,
            storage_encoding=storage_encoding,
        )
        self._ledger._versions_by_object_id[raw_object.id] = [version]
        updated_raw_object = replace(
            raw_object,
            last_checked_at=fetched_at,
            revalidation=revalidation,
        )
        for key, candidate in self._ledger._raw_objects_by_key.items():
            if candidate.id == raw_object.id:
                self._ledger._raw_objects_by_key[key] = updated_raw_object
                break
        return RotateVersionResult(
            raw_object=updated_raw_object,
            version=version,
            stale_versions=stale_versions,
        )


class InMemoryFetchPlanResolver:
    def __init__(self, ledger: InMemoryRawObjectLedger, reader: InMemoryRawObjectReader) -> None:
        self._ledger = ledger
        self._reader = reader

    def resolve_fetch_plan(self, base_plan: BaseFetchPlan) -> FetchPlan:
        return self.resolve_fetch_plans([base_plan])[0]

    def resolve_fetch_plans(self, base_plans: list[BaseFetchPlan]) -> list[FetchPlan]:
        self._ledger.resolve_fetch_plans_calls += 1
        resolved_plans: list[FetchPlan] = []
        for base_plan in base_plans:
            raw_object = self._reader.load_raw_object(ref=base_plan.ref)
            if raw_object is not None and raw_object.ref.update_mode is not base_plan.update_mode:
                raise ValueError(
                    "raw object update_mode mismatch: "
                    f"stored={raw_object.ref.update_mode.value} requested={base_plan.update_mode.value}"
                )
            if raw_object is None:
                resolved: FetchPlan = UnresolvedFetchPlan(
                    ref=base_plan.ref,
                    source_url=base_plan.source_url,
                    source_relative_path=base_plan.source_relative_path,
                    update_mode=base_plan.update_mode,
                    identity_key=base_plan.identity_key,
                    temp_path=base_plan.temp_path,
                )
            else:
                current_version = self._ledger._versions_by_object_id.get(raw_object.id, [None])[0]
                if current_version is None:
                    raise RuntimeError(f"Ledger corruption: raw_object {raw_object.id} exists but has no versions")
                resolved = ResolvedFetchPlan(
                    ref=base_plan.ref,
                    source_url=base_plan.source_url,
                    source_relative_path=base_plan.source_relative_path,
                    update_mode=base_plan.update_mode,
                    identity_key=base_plan.identity_key,
                    temp_path=base_plan.temp_path,
                    raw_object=raw_object,
                    current_version=current_version,
                )
            resolved_plans.append(resolved)
        return resolved_plans


class InMemoryPublicationTrackerTx:
    def __init__(self, ledger: InMemoryRawObjectLedger) -> None:
        self._ledger = ledger

    def mark_published(
        self,
        *,
        ref: RawObjectRef,
        sha256: str,
        version_id: str,
        context: PublicationContext,
    ) -> None:
        self._ledger._publications.add((*ref.group_key, ref.identity_hash, sha256))

    def mark_published_many(
        self,
        publications: list[tuple[RawObjectRef, str, str, PublicationContext]],
    ) -> None:
        for ref, sha256, version_id, ctx in publications:
            self._ledger._publications.add((*ref.group_key, ref.identity_hash, sha256))

    def is_published(
        self,
        *,
        ref: RawObjectRef,
        sha256: str,
    ) -> bool:
        return (*ref.group_key, ref.identity_hash, sha256) in self._ledger._publications

    def filter_published(
        self,
        *,
        group_key: tuple[str, str],
        versions: list[tuple[str, str]],
    ) -> set[tuple[str, str]]:
        self._ledger.filter_published_calls += 1
        return {
            (identity_hash, sha256)
            for identity_hash, sha256 in versions
            if (*group_key, identity_hash, sha256) in self._ledger._publications
        }


class InMemoryRawObjectLedger:
    def __init__(self) -> None:
        self._raw_objects_by_key: dict[tuple[str, str, str], RawObjectEntry] = {}
        self._versions_by_object_id: dict[str, list[RawObjectVersion]] = {}
        self._publications: set[tuple[str, str, str, str]] = set()
        self.resolve_fetch_plans_calls = 0
        self.filter_published_calls = 0

    def close(self) -> None:
        return None

    @contextmanager
    def transaction(self) -> Iterator[LedgerTx]:
        reader = InMemoryRawObjectReader(self)
        yield LedgerTx(
            reader=reader,
            writer=InMemoryRawObjectWriter(self),
            resolver=InMemoryFetchPlanResolver(self, reader=reader),
            publications=InMemoryPublicationTrackerTx(self),
        )
