from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import Any, ContextManager, Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from ingest.cache.identity import canonical_identity_json
from ingest.cache.models import RawObject, RawObjectVersion, UpdateMode


class RawObjectLedgerProtocol(Protocol):
    def open(self) -> None: ...

    def close(self) -> None: ...

    def transaction(self) -> ContextManager[None]: ...

    def load_raw_object(
        self,
        *,
        source_name: str,
        dataset_name: str,
        identity_hash: str,
    ) -> RawObject | None: ...

    def load_latest_version(self, raw_object_id: str) -> RawObjectVersion | None: ...

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
    ) -> RawObject: ...

    def insert_version(self, version: RawObjectVersion) -> None: ...

    def list_versions(self, raw_object_id: str) -> list[RawObjectVersion]: ...

    def delete_versions(self, version_ids: list[str]) -> None: ...

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
    ) -> None: ...

    def is_published(
        self,
        *,
        source_name: str,
        dataset_name: str,
        identity_hash: str,
        sha256: str,
    ) -> bool: ...


class RawObjectLedger:
    def __init__(self, *, ledger_url: str) -> None:
        self._ledger_url = ledger_url
        self._con: psycopg.Connection[Any] | None = None

    def open(self) -> None:
        self._con = _connect(self._ledger_url)
        self._bootstrap()

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
        self._con = None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        con = self._require_open()
        try:
            yield
        except Exception:
            con.rollback()
            raise
        else:
            con.commit()

    def load_raw_object(
        self,
        *,
        source_name: str,
        dataset_name: str,
        identity_hash: str,
    ) -> RawObject | None:
        row = self._fetchone(
            """
            select *
            from raw_objects
            where source_name = ? and dataset_name = ? and identity_hash = ?
            """,
            (source_name, dataset_name, identity_hash),
        )
        if row is None:
            return None
        return _row_to_raw_object(row)

    def load_latest_version(self, raw_object_id: str) -> RawObjectVersion | None:
        row = self._fetchone(
            """
            select *
            from raw_object_versions
            where raw_object_id = ?
            order by fetched_at desc, id desc
            limit 1
            """,
            (raw_object_id,),
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
    ) -> RawObject:
        existing = self.load_raw_object(
            source_name=source_name,
            dataset_name=dataset_name,
            identity_hash=identity_hash,
        )
        if existing is None:
            raw_object = RawObject(
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
                """
                insert into raw_objects (
                    id,
                    source_name,
                    dataset_name,
                    identity_key_json,
                    identity_hash,
                    update_mode,
                    created_at,
                    last_checked_at,
                    last_seen_etag,
                    last_seen_last_modified,
                    last_seen_content_length
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    raw_object.id,
                    raw_object.source_name,
                    raw_object.dataset_name,
                    canonical_identity_json(raw_object.identity_key),
                    raw_object.identity_hash,
                    raw_object.update_mode.value,
                    raw_object.created_at.isoformat(),
                    raw_object.last_checked_at.isoformat()
                    if raw_object.last_checked_at
                    else None,
                    raw_object.last_seen_etag,
                    raw_object.last_seen_last_modified,
                    raw_object.last_seen_content_length,
                ),
            )
            return raw_object

        self._execute(
            """
            update raw_objects
            set last_checked_at = ?,
                last_seen_etag = ?,
                last_seen_last_modified = ?,
                last_seen_content_length = ?
            where id = ?
            """,
            (
                checked_at.isoformat(),
                current_version.etag if current_version else existing.last_seen_etag,
                current_version.last_modified
                if current_version
                else existing.last_seen_last_modified,
                current_version.content_length
                if current_version
                else existing.last_seen_content_length,
                existing.id,
            ),
        )
        return replace(existing, last_checked_at=checked_at)

    def insert_version(self, version: RawObjectVersion) -> None:
        self._execute(
            """
            insert into raw_object_versions (
                id,
                raw_object_id,
                source_url,
                fetched_at,
                etag,
                last_modified,
                content_length,
                sha256,
                local_path,
                storage_encoding
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version.id,
                version.raw_object_id,
                version.source_url,
                version.fetched_at.isoformat(),
                version.etag,
                version.last_modified,
                version.content_length,
                version.sha256,
                version.local_path,
                version.storage_encoding,
            ),
        )
        self._execute(
            """
            update raw_objects
            set last_seen_etag = ?,
                last_seen_last_modified = ?,
                last_seen_content_length = ?
            where id = ?
            """,
            (
                version.etag,
                version.last_modified,
                version.content_length,
                version.raw_object_id,
            ),
        )

    def list_versions(self, raw_object_id: str) -> list[RawObjectVersion]:
        rows = self._fetchall(
            """
            select *
            from raw_object_versions
            where raw_object_id = ?
            order by fetched_at desc, id desc
            """,
            (raw_object_id,),
        )
        return [_row_to_raw_object_version(row) for row in rows]

    def delete_versions(self, version_ids: list[str]) -> None:
        for version_id in version_ids:
            self._execute("delete from raw_object_versions where id = ?", (version_id,))

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
        self._execute(
            """
            insert into raw_object_publications (
                id,
                source_name,
                dataset_name,
                identity_hash,
                sha256,
                version_id,
                published_at,
                publication_scope,
                publisher_run_id
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict (source_name, dataset_name, identity_hash, sha256) do nothing
            """,
            (
                uuid4().hex,
                source_name,
                dataset_name,
                identity_hash,
                sha256,
                version_id,
                published_at.isoformat(),
                publication_scope,
                publisher_run_id,
            ),
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
            """
            select id
            from raw_object_publications
            where source_name = ?
                and dataset_name = ?
                and identity_hash = ?
                and sha256 = ?
            """,
            (source_name, dataset_name, identity_hash, sha256),
        )
        return row is not None

    def _bootstrap(self) -> None:
        with self.transaction():
            self._execute(
                """
                create table if not exists raw_objects (
                    id text primary key,
                    source_name text not null,
                    dataset_name text not null,
                    identity_key_json text not null,
                    identity_hash text not null,
                    update_mode text not null,
                    created_at text not null,
                    last_checked_at text,
                    last_seen_etag text,
                    last_seen_last_modified text,
                    last_seen_content_length integer,
                    unique (source_name, dataset_name, identity_hash)
                )
                """
            )
            self._execute(
                """
                create table if not exists raw_object_versions (
                    id text primary key,
                    raw_object_id text not null,
                    source_url text not null,
                    fetched_at text not null,
                    etag text,
                    last_modified text,
                    content_length integer,
                    sha256 text not null,
                    local_path text not null,
                    storage_encoding text not null,
                    foreign key (raw_object_id) references raw_objects (id) on delete cascade
                )
                """
            )
            self._execute(
                """
                create index if not exists raw_object_versions_latest_idx
                on raw_object_versions (raw_object_id, fetched_at desc, id desc)
                """
            )
            self._execute(
                """
                create table if not exists raw_object_publications (
                    id text primary key,
                    source_name text not null,
                    dataset_name text not null,
                    identity_hash text not null,
                    sha256 text not null,
                    version_id text not null,
                    published_at text not null,
                    publication_scope text,
                    publisher_run_id text,
                    unique (source_name, dataset_name, identity_hash, sha256)
                )
                """
            )

    def _execute(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        con = self._require_open()
        sql = _prepare_query(query)
        return con.execute(sql, params)

    def _fetchone(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        row = self._execute(query, params).fetchone()
        if row is None:
            return None
        return dict(row)

    def _fetchall(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        rows = self._execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def _require_open(self) -> psycopg.Connection[Any]:
        if self._con is None:
            raise RuntimeError("RawObjectLedger must be opened before use")
        return self._con


def _connect(ledger_url: str) -> psycopg.Connection[Any]:
    if ledger_url.startswith("postgresql://") or ledger_url.startswith("postgres://"):
        return psycopg.connect(ledger_url, row_factory=dict_row)
    raise ValueError("ledger_url must be a PostgreSQL URL")


def _prepare_query(query: str) -> str:
    normalized = "\n".join(line.rstrip() for line in query.strip().splitlines())
    return normalized.replace("?", "%s")


def _row_to_raw_object(row: Mapping[str, Any]) -> RawObject:
    return RawObject(
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
