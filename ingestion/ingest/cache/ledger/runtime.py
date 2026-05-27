from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from types import TracebackType
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, delete, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, RowMapping

from ingest.cache.ledger.mappers import (
    normalize_ledger_url,
    raw_object_publication_values,
    raw_object_seen_values,
    raw_object_values,
    raw_object_version_values,
    require_update_mode,
    row_to_raw_object,
    row_to_raw_object_version,
)
from ingest.cache.ledger.schema import (
    _METADATA,
    raw_object_publications,
    raw_object_versions,
    raw_objects,
)
from ingest.cache.ledger.types import ReplaceCurrentVersionResult
from ingest.cache.models import (
    BaseFetchPlan,
    PublicationContext,
    RawObjectDefinition,
    RawObjectEntry,
    RawObjectRef,
    RawObjectVersion,
    RevalidationMetadata,
    ResolvedFetchPlan,
)


class RawObjectLedger:
    def __init__(self, *, ledger_url: str) -> None:
        self._engine = create_engine(normalize_ledger_url(ledger_url))
        self._bootstrapped = False

    def __enter__(self) -> RawObjectLedger:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._engine.dispose()

    @contextmanager
    def transaction(self) -> Iterator[RawObjectLedgerTx]:
        self._bootstrap()
        with self._engine.begin() as con:
            yield RawObjectLedgerTx(con)

    def _bootstrap(self) -> None:
        if self._bootstrapped:
            return
        with self._engine.begin() as con:
            _METADATA.create_all(con)
        self._bootstrapped = True


class RawObjectLedgerTx:
    def __init__(self, con: Connection) -> None:
        self._con = con

    def load_raw_object(
        self,
        *,
        ref: RawObjectRef,
    ) -> RawObjectEntry | None:
        row = self._fetchone(
            select(raw_objects).where(
                raw_objects.c.source_name == ref.source_name,
                raw_objects.c.dataset_name == ref.dataset_name,
                raw_objects.c.identity_hash == ref.identity_hash,
            )
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
        rows = self._fetchall(
            select(raw_objects).where(
                raw_objects.c.source_name == source_name,
                raw_objects.c.dataset_name == dataset_name,
                raw_objects.c.identity_hash.in_(identity_hashes),
            )
        )
        return {
            raw_object.identity_hash: raw_object
            for raw_object in (row_to_raw_object(row) for row in rows)
        }

    def load_latest_version(self, raw_object_id: str) -> RawObjectVersion | None:
        row = self._fetchone(
            select(raw_object_versions).where(
                raw_object_versions.c.raw_object_id == raw_object_id
            )
        )
        if row is None:
            return None
        return row_to_raw_object_version(row)

    def load_latest_versions(
        self, raw_object_ids: list[str]
    ) -> dict[str, RawObjectVersion]:
        if not raw_object_ids:
            return {}
        rows = self._fetchall(
            select(raw_object_versions).where(
                raw_object_versions.c.raw_object_id.in_(raw_object_ids)
            )
        )
        return {
            version.raw_object_id: version
            for version in (row_to_raw_object_version(row) for row in rows)
        }

    def resolve_fetch_plan(self, base_plan: BaseFetchPlan) -> ResolvedFetchPlan:
        return self.resolve_fetch_plans([base_plan])[0]

    def resolve_fetch_plans(
        self, base_plans: list[BaseFetchPlan]
    ) -> list[ResolvedFetchPlan]:
        if not base_plans:
            return []

        grouped_plans: dict[tuple[str, str], list[BaseFetchPlan]] = {}
        for base_plan in base_plans:
            grouped_plans.setdefault(base_plan.ref.group_key, []).append(base_plan)

        resolved_by_identity: dict[tuple[str, str, str], ResolvedFetchPlan] = {}
        for (source_name, dataset_name), plans in grouped_plans.items():
            raw_objects = self.load_raw_objects(
                group_key=(source_name, dataset_name),
                identity_hashes=[plan.identity_hash for plan in plans],
            )
            current_versions = self.load_latest_versions(
                [raw_object.id for raw_object in raw_objects.values()]
            )
            for plan in plans:
                raw_object = raw_objects.get(plan.identity_hash)
                require_update_mode(raw_object, plan.update_mode)
                current_version = (
                    current_versions.get(raw_object.id)
                    if raw_object is not None
                    else None
                )
                resolved_by_identity[
                    (source_name, dataset_name, plan.identity_hash)
                ] = ResolvedFetchPlan(
                    source_name=plan.source_name,
                    dataset_name=plan.dataset_name,
                    source_url=plan.source_url,
                    source_relative_path=plan.source_relative_path,
                    update_mode=plan.update_mode,
                    identity_key=plan.identity_key,
                    identity_hash=plan.identity_hash,
                    temp_path=plan.temp_path,
                    raw_object=raw_object,
                    current_version=current_version,
                )

        return [
            resolved_by_identity[
                (plan.source_name, plan.dataset_name, plan.identity_hash)
            ]
            for plan in base_plans
        ]

    def touch_raw_object(
        self,
        *,
        definition: RawObjectDefinition,
        checked_at: datetime,
        revalidation: RevalidationMetadata | None = None,
    ) -> RawObjectEntry:
        existing = self.load_raw_object(ref=definition.ref)
        revalidation = revalidation or RevalidationMetadata()
        if existing is None:
            raw_object = RawObjectEntry(
                id=uuid4().hex,
                source_name=definition.ref.source_name,
                dataset_name=definition.ref.dataset_name,
                identity_key=dict(definition.identity_key),
                identity_hash=definition.ref.identity_hash,
                update_mode=definition.update_mode,
                created_at=checked_at,
                last_checked_at=checked_at,
                revalidation=revalidation,
            )
            self._execute(raw_objects.insert().values(**raw_object_values(raw_object)))
            return raw_object

        updated = replace(
            existing,
            last_checked_at=checked_at,
            revalidation=_merge_revalidation(existing.revalidation, revalidation),
        )
        self._execute(
            update(raw_objects)
            .where(raw_objects.c.id == existing.id)
            .values(**raw_object_seen_values(updated))
        )
        return updated

    def replace_current_version(
        self,
        *,
        definition: RawObjectDefinition,
        source_url: str,
        fetched_at: datetime,
        revalidation: RevalidationMetadata,
        sha256: str,
        local_path: str,
        storage_encoding: str,
    ) -> ReplaceCurrentVersionResult:
        raw_object = self.touch_raw_object(
            definition=definition,
            checked_at=fetched_at,
            revalidation=revalidation,
        )
        stale_versions = self._list_versions(raw_object.id)
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
        self._execute(
            raw_object_versions.insert().values(**raw_object_version_values(version))
        )
        if stale_versions:
            self._execute(
                delete(raw_object_versions).where(
                    raw_object_versions.c.id.in_([stale.id for stale in stale_versions])
                )
            )
        return ReplaceCurrentVersionResult(
            raw_object=replace(
                raw_object,
                last_checked_at=fetched_at,
                revalidation=revalidation,
            ),
            version=version,
            stale_versions=stale_versions,
        )

    def mark_published(
        self,
        *,
        ref: RawObjectRef,
        sha256: str,
        version_id: str,
        context: PublicationContext,
    ) -> None:
        statement = pg_insert(raw_object_publications).values(
            **raw_object_publication_values(
                ref=ref,
                sha256=sha256,
                version_id=version_id,
                context=context,
            )
        )
        self._execute(
            statement.on_conflict_do_nothing(
                index_elements=[
                    raw_object_publications.c.source_name,
                    raw_object_publications.c.dataset_name,
                    raw_object_publications.c.identity_hash,
                    raw_object_publications.c.sha256,
                ]
            )
        )

    def is_published(
        self,
        *,
        ref: RawObjectRef,
        sha256: str,
    ) -> bool:
        row = self._fetchone(
            select(raw_object_publications.c.id).where(
                raw_object_publications.c.source_name == ref.source_name,
                raw_object_publications.c.dataset_name == ref.dataset_name,
                raw_object_publications.c.identity_hash == ref.identity_hash,
                raw_object_publications.c.sha256 == sha256,
            )
        )
        return row is not None

    def filter_published(
        self,
        *,
        group_key: tuple[str, str],
        versions: list[tuple[str, str]],
    ) -> set[tuple[str, str]]:
        if not versions:
            return set()
        source_name, dataset_name = group_key
        rows = self._fetchall(
            select(
                raw_object_publications.c.identity_hash,
                raw_object_publications.c.sha256,
            ).where(
                raw_object_publications.c.source_name == source_name,
                raw_object_publications.c.dataset_name == dataset_name,
                tuple_(
                    raw_object_publications.c.identity_hash,
                    raw_object_publications.c.sha256,
                ).in_(versions),
            )
        )
        return {(row["identity_hash"], row["sha256"]) for row in rows}

    def _execute(self, statement: Any) -> Any:
        return self._con.execute(statement)

    def _fetchone(self, statement: Any) -> RowMapping | None:
        return self._execute(statement).mappings().first()

    def _fetchall(self, statement: Any) -> list[RowMapping]:
        return list(self._execute(statement).mappings().all())

    def _list_versions(self, raw_object_id: str) -> list[RawObjectVersion]:
        rows = self._fetchall(
            select(raw_object_versions).where(
                raw_object_versions.c.raw_object_id == raw_object_id
            )
        )
        return [row_to_raw_object_version(row) for row in rows]


def _merge_revalidation(
    existing: RevalidationMetadata, incoming: RevalidationMetadata
) -> RevalidationMetadata:
    return RevalidationMetadata(
        etag=incoming.etag if incoming.etag is not None else existing.etag,
        last_modified=(
            incoming.last_modified
            if incoming.last_modified is not None
            else existing.last_modified
        ),
        content_length=(
            incoming.content_length
            if incoming.content_length is not None
            else existing.content_length
        ),
    )
