"""DB-API repository for raw source-file acquisition ledger."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from ingest.raw_files.config import sqlite_path_from_ledger_url
from ingest.raw_files.models import RawFileRecord


class DbApiCursor(Protocol):
    description: Sequence[Sequence[Any]] | None
    lastrowid: int | None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> "DbApiCursor": ...
    def fetchone(self) -> Any: ...
    def fetchall(self) -> list[Any]: ...


class DbApiConnection(Protocol):
    def __enter__(self) -> "DbApiConnection": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> object: ...
    def execute(self, sql: str, params: Sequence[Any] = ()) -> DbApiCursor: ...


Connect = Callable[[], DbApiConnection]


class RawFileRepositoryProtocol(Protocol):
    def find_latest_success(
        self,
        *,
        source_name: str,
        dataset_name: str,
        source_date: str,
        source_url: str,
    ) -> RawFileRecord | None: ...
    def insert(self, record: RawFileRecord) -> RawFileRecord: ...
    def list_successes_for_source_date(
        self,
        *,
        source_name: str,
        dataset_name: str,
        source_date: str,
    ) -> list[RawFileRecord]: ...
    def delete_successes_for_local_paths(self, local_paths: set[str]) -> None: ...
    def touch_checked(self, record_id: int, checked_at: str) -> None: ...


class RawFileRepository:
    """Persist raw source-file acquisition metadata through DB-API."""

    def __init__(self, ledger_url: str) -> None:
        self.ledger_url = ledger_url
        self._backend = _backend_for_ledger_url(self.ledger_url)
        self._init_db()

    def find_latest_success(
        self,
        *,
        source_name: str,
        dataset_name: str,
        source_date: str,
        source_url: str,
    ) -> RawFileRecord | None:
        """Return latest successful acquisition for a source file."""
        with self._backend.connect() as conn:
            cursor = conn.execute(
                self._backend.sql(
                    """
                    select *
                    from raw_file_acquisitions
                    where source_name = ?
                      and dataset_name = ?
                      and source_date = ?
                      and source_url = ?
                      and status = 'downloaded'
                    order by downloaded_at desc, id desc
                    limit 1
                    """
                ),
                (source_name, dataset_name, source_date, source_url),
            )
            row = cursor.fetchone()
        return _record_from_row(row, cursor.description) if row is not None else None

    def insert(self, record: RawFileRecord) -> RawFileRecord:
        """Insert an acquisition row and return it with database id."""
        with self._backend.connect() as conn:
            cursor = conn.execute(
                self._backend.sql(
                    f"""
                    insert into raw_file_acquisitions (
                        source_name,
                        dataset_name,
                        source_date,
                        source_url,
                        local_path,
                        sha256,
                        content_length,
                        downloaded_size,
                        last_modified,
                        first_seen_at,
                        last_checked_at,
                        downloaded_at,
                        status,
                        error_message
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    {self._backend.returning_id_clause}
                    """
                ),
                (
                    record.source_name,
                    record.dataset_name,
                    record.source_date,
                    record.source_url,
                    record.local_path,
                    record.sha256,
                    record.content_length,
                    record.downloaded_size,
                    record.last_modified,
                    record.first_seen_at,
                    record.last_checked_at,
                    record.downloaded_at,
                    record.status,
                    record.error_message,
                ),
            )
            record_id = self._backend.inserted_id(cursor)
        return RawFileRecord(
            id=record_id, **{k: v for k, v in vars(record).items() if k != "id"}
        )

    def list_successes_for_source_date(
        self,
        *,
        source_name: str,
        dataset_name: str,
        source_date: str,
    ) -> list[RawFileRecord]:
        """Return successful acquisitions for a source date, newest first."""
        with self._backend.connect() as conn:
            cursor = conn.execute(
                self._backend.sql(
                    """
                    select *
                    from raw_file_acquisitions
                    where source_name = ?
                      and dataset_name = ?
                      and source_date = ?
                      and status = 'downloaded'
                      and local_path is not null
                    order by downloaded_at desc, id desc
                    """
                ),
                (source_name, dataset_name, source_date),
            )
            rows = cursor.fetchall()
        return [_record_from_row(row, cursor.description) for row in rows]

    def delete_successes_for_local_paths(self, local_paths: set[str]) -> None:
        """Delete successful ledger rows for removed local files."""
        if not local_paths:
            return

        placeholders = ", ".join("?" for _ in local_paths)
        with self._backend.connect() as conn:
            conn.execute(
                self._backend.sql(
                    f"""
                    delete from raw_file_acquisitions
                    where status = 'downloaded'
                      and local_path in ({placeholders})
                    """
                ),
                tuple(sorted(local_paths)),
            )

    def touch_checked(self, record_id: int, checked_at: str) -> None:
        """Update last_checked_at for a cache-hit row."""
        with self._backend.connect() as conn:
            conn.execute(
                self._backend.sql(
                    """
                    update raw_file_acquisitions
                    set last_checked_at = ?
                    where id = ?
                    """
                ),
                (checked_at, record_id),
            )

    def _init_db(self) -> None:
        with self._backend.connect() as conn:
            conn.execute(self._backend.create_table_sql)
            conn.execute(
                """
                create index if not exists idx_raw_file_success_lookup
                on raw_file_acquisitions (
                    source_name,
                    dataset_name,
                    source_date,
                    source_url,
                    status,
                    downloaded_at
                )
                """
            )


class _Backend:
    def __init__(
        self,
        *,
        connect: Connect,
        placeholder: str,
        create_table_sql: str,
        returning_id_clause: str = "",
    ) -> None:
        self.connect = connect
        self.placeholder = placeholder
        self.create_table_sql = create_table_sql
        self.returning_id_clause = returning_id_clause

    def sql(self, query: str) -> str:
        if self.placeholder == "?":
            return query
        return query.replace("?", self.placeholder)

    def inserted_id(self, cursor: DbApiCursor) -> int | None:
        if self.returning_id_clause:
            row = cursor.fetchone()
            if row is None:
                return None
            return int(row[0] if not isinstance(row, dict) else row["id"])
        return cursor.lastrowid


def create_raw_file_repository(ledger_url: str) -> RawFileRepository:
    """Build raw file ledger repository for SQLite or PostgreSQL URL."""
    return RawFileRepository(ledger_url)


def _backend_for_ledger_url(ledger_url: str) -> _Backend:
    parsed = urlparse(ledger_url)
    if parsed.scheme == "sqlite":
        sqlite_path = sqlite_path_from_ledger_url(ledger_url)
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return _Backend(
            connect=lambda: _connect_sqlite(sqlite_path),
            placeholder="?",
            create_table_sql="""
                create table if not exists raw_file_acquisitions (
                    id integer primary key autoincrement,
                    source_name text not null,
                    dataset_name text not null,
                    source_date text not null,
                    source_url text not null,
                    local_path text,
                    sha256 text,
                    content_length integer,
                    downloaded_size integer,
                    last_modified text,
                    first_seen_at text not null,
                    last_checked_at text not null,
                    downloaded_at text,
                    status text not null,
                    error_message text
                )
                """,
        )
    if parsed.scheme in {"postgres", "postgresql"}:
        return _Backend(
            connect=lambda: _connect_postgres(ledger_url),
            placeholder="%s",
            returning_id_clause="returning id",
            create_table_sql="""
                create table if not exists raw_file_acquisitions (
                    id bigserial primary key,
                    source_name text not null,
                    dataset_name text not null,
                    source_date text not null,
                    source_url text not null,
                    local_path text,
                    sha256 text,
                    content_length integer,
                    downloaded_size integer,
                    last_modified text,
                    first_seen_at text not null,
                    last_checked_at text not null,
                    downloaded_at text,
                    status text not null,
                    error_message text
                )
                """,
        )

    msg = "raw file ledger URL must use sqlite, postgres, or postgresql scheme"
    raise ValueError(msg)


def _connect_sqlite(sqlite_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma busy_timeout = 5000")
    return conn


def _connect_postgres(ledger_url: str) -> DbApiConnection:
    import psycopg

    return psycopg.connect(ledger_url)


def _record_from_row(
    row: Any, description: Sequence[Sequence[Any]] | None
) -> RawFileRecord:
    if isinstance(row, dict):
        values = row
    elif isinstance(row, sqlite3.Row):
        values = dict(row)
    else:
        if description is None:
            msg = "DB-API cursor description required for tuple rows"
            raise RuntimeError(msg)
        values = {
            _column_name(column): value
            for column, value in zip(description, row, strict=True)
        }
    return RawFileRecord(**values)


def _column_name(column: Any) -> str:
    name = getattr(column, "name", None)
    if name is not None:
        return str(name)
    return str(column[0])
