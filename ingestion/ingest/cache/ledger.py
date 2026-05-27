from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from ingest.cache.identity import canonical_identity_json
from ingest.cache.models import RawObjectEntry, RawObjectVersion, UpdateMode


_METADATA = MetaData()

raw_objects = Table(
    "raw_objects",
    _METADATA,
    Column("id", Text, primary_key=True),
    Column("source_name", Text, nullable=False),
    Column("dataset_name", Text, nullable=False),
    Column("identity_key_json", Text, nullable=False),
    Column("identity_hash", Text, nullable=False),
    Column("update_mode", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("last_checked_at", Text),
    Column("last_seen_etag", Text),
    Column("last_seen_last_modified", Text),
    Column("last_seen_content_length", Integer),
    UniqueConstraint(
        "source_name",
        "dataset_name",
        "identity_hash",
        name="raw_objects_source_dataset_identity_key",
    ),
)

raw_object_versions = Table(
    "raw_object_versions",
    _METADATA,
    Column("id", Text, primary_key=True),
    Column(
        "raw_object_id",
        Text,
        ForeignKey("raw_objects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("source_url", Text, nullable=False),
    Column("fetched_at", Text, nullable=False),
    Column("etag", Text),
    Column("last_modified", Text),
    Column("content_length", Integer),
    Column("sha256", Text, nullable=False),
    Column("local_path", Text, nullable=False),
    Column("storage_encoding", Text, nullable=False),
)

raw_object_publications = Table(
    "raw_object_publications",
    _METADATA,
    Column("id", Text, primary_key=True),
    Column("source_name", Text, nullable=False),
    Column("dataset_name", Text, nullable=False),
    Column("identity_hash", Text, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("version_id", Text, nullable=False),
    Column("published_at", Text, nullable=False),
    Column("publication_scope", Text),
    Column("publisher_run_id", Text),
    UniqueConstraint(
        "source_name",
        "dataset_name",
        "identity_hash",
        "sha256",
        name="raw_object_publications_unique_version",
    ),
)

Index(
    "raw_object_versions_latest_idx",
    raw_object_versions.c.raw_object_id,
    raw_object_versions.c.fetched_at.desc(),
    raw_object_versions.c.id.desc(),
)


class RawObjectLedger:
    def __init__(self, *, ledger_url: str) -> None:
        self._ledger_url = ledger_url
        self._engine: Engine | None = None
        self._con: Connection | None = None

    def open(self) -> None:
        self._engine = create_engine(_normalize_ledger_url(self._ledger_url))
        self._con = self._engine.connect()
        self._bootstrap()

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
        if self._engine is not None:
            self._engine.dispose()
        self._con = None
        self._engine = None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        con = self._require_open()
        with con.begin():
            yield

    def load_raw_object(
        self,
        *,
        source_name: str,
        dataset_name: str,
        identity_hash: str,
    ) -> RawObjectEntry | None:
        row = self._fetchone(
            select(raw_objects).where(
                raw_objects.c.source_name == source_name,
                raw_objects.c.dataset_name == dataset_name,
                raw_objects.c.identity_hash == identity_hash,
            )
        )
        if row is None:
            return None
        return _row_to_raw_object(row)

    def load_latest_version(self, raw_object_id: str) -> RawObjectVersion | None:
        row = self._fetchone(
            select(raw_object_versions)
            .where(raw_object_versions.c.raw_object_id == raw_object_id)
            .order_by(
                raw_object_versions.c.fetched_at.desc(),
                raw_object_versions.c.id.desc(),
            )
            .limit(1)
        )
        if row is None:
            return None
        return _row_to_raw_object_version(row)

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
        existing = self.load_raw_object(
            source_name=source_name,
            dataset_name=dataset_name,
            identity_hash=identity_hash,
        )
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
            self._execute(
                raw_objects.insert().values(
                    id=raw_object.id,
                    source_name=raw_object.source_name,
                    dataset_name=raw_object.dataset_name,
                    identity_key_json=canonical_identity_json(raw_object.identity_key),
                    identity_hash=raw_object.identity_hash,
                    update_mode=raw_object.update_mode.value,
                    created_at=raw_object.created_at.isoformat(),
                    last_checked_at=raw_object.last_checked_at.isoformat()
                    if raw_object.last_checked_at
                    else None,
                    last_seen_etag=raw_object.last_seen_etag,
                    last_seen_last_modified=raw_object.last_seen_last_modified,
                    last_seen_content_length=raw_object.last_seen_content_length,
                )
            )
            return raw_object

        self._execute(
            update(raw_objects)
            .where(raw_objects.c.id == existing.id)
            .values(
                last_checked_at=checked_at.isoformat(),
                last_seen_etag=current_version.etag
                if current_version
                else existing.last_seen_etag,
                last_seen_last_modified=current_version.last_modified
                if current_version
                else existing.last_seen_last_modified,
                last_seen_content_length=current_version.content_length
                if current_version
                else existing.last_seen_content_length,
            )
        )
        return replace(existing, last_checked_at=checked_at)

    def insert_version(self, version: RawObjectVersion) -> None:
        self._execute(
            raw_object_versions.insert().values(
                id=version.id,
                raw_object_id=version.raw_object_id,
                source_url=version.source_url,
                fetched_at=version.fetched_at.isoformat(),
                etag=version.etag,
                last_modified=version.last_modified,
                content_length=version.content_length,
                sha256=version.sha256,
                local_path=version.local_path,
                storage_encoding=version.storage_encoding,
            )
        )
        self._execute(
            update(raw_objects)
            .where(raw_objects.c.id == version.raw_object_id)
            .values(
                last_seen_etag=version.etag,
                last_seen_last_modified=version.last_modified,
                last_seen_content_length=version.content_length,
            )
        )

    def list_versions(self, raw_object_id: str) -> list[RawObjectVersion]:
        rows = self._fetchall(
            select(raw_object_versions)
            .where(raw_object_versions.c.raw_object_id == raw_object_id)
            .order_by(
                raw_object_versions.c.fetched_at.desc(),
                raw_object_versions.c.id.desc(),
            )
        )
        return [_row_to_raw_object_version(row) for row in rows]

    def delete_versions(self, version_ids: list[str]) -> None:
        if not version_ids:
            return
        self._execute(
            delete(raw_object_versions).where(raw_object_versions.c.id.in_(version_ids))
        )

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
        statement = pg_insert(raw_object_publications).values(
            id=uuid4().hex,
            source_name=source_name,
            dataset_name=dataset_name,
            identity_hash=identity_hash,
            sha256=sha256,
            version_id=version_id,
            published_at=published_at.isoformat(),
            publication_scope=publication_scope,
            publisher_run_id=publisher_run_id,
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
        source_name: str,
        dataset_name: str,
        identity_hash: str,
        sha256: str,
    ) -> bool:
        row = self._fetchone(
            select(raw_object_publications.c.id).where(
                raw_object_publications.c.source_name == source_name,
                raw_object_publications.c.dataset_name == dataset_name,
                raw_object_publications.c.identity_hash == identity_hash,
                raw_object_publications.c.sha256 == sha256,
            )
        )
        return row is not None

    def _bootstrap(self) -> None:
        con = self._require_open()
        _METADATA.create_all(con)
        con.commit()

    def _execute(self, statement: Any) -> Any:
        return self._require_open().execute(statement)

    def _fetchone(self, statement: Any) -> dict[str, Any] | None:
        row = self._execute(statement).mappings().first()
        if row is None:
            return None
        return dict(row)

    def _fetchall(self, statement: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in self._execute(statement).mappings().all()]

    def _require_open(self) -> Connection:
        if self._con is None:
            raise RuntimeError("RawObjectLedger must be opened before use")
        return self._con


def _normalize_ledger_url(ledger_url: str) -> str:
    if ledger_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + ledger_url.removeprefix("postgresql://")
    if ledger_url.startswith("postgres://"):
        return "postgresql+psycopg://" + ledger_url.removeprefix("postgres://")
    raise ValueError("ledger_url must be a PostgreSQL URL")


def _row_to_raw_object(row: Mapping[str, Any]) -> RawObjectEntry:
    return RawObjectEntry(
        id=row["id"],
        source_name=row["source_name"],
        dataset_name=row["dataset_name"],
        identity_key=json.loads(row["identity_key_json"]),
        identity_hash=row["identity_hash"],
        update_mode=UpdateMode(row["update_mode"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        last_checked_at=(
            datetime.fromisoformat(row["last_checked_at"])
            if row["last_checked_at"]
            else None
        ),
        last_seen_etag=row["last_seen_etag"],
        last_seen_last_modified=row["last_seen_last_modified"],
        last_seen_content_length=row["last_seen_content_length"],
    )


def _row_to_raw_object_version(row: Mapping[str, Any]) -> RawObjectVersion:
    return RawObjectVersion(
        id=row["id"],
        raw_object_id=row["raw_object_id"],
        source_url=row["source_url"],
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        etag=row["etag"],
        last_modified=row["last_modified"],
        content_length=row["content_length"],
        sha256=row["sha256"],
        local_path=row["local_path"],
        storage_encoding=row["storage_encoding"],
    )
