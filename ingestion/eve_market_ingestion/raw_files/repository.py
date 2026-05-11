"""SQLite repository for raw source-file acquisition ledger."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from eve_market_ingestion.raw_files.models import RawFileRecord


class RawFileRepository:
    """Persist raw source-file acquisition metadata in SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
        with self._connect() as conn:
            row = conn.execute(
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
                """,
                (source_name, dataset_name, source_date, source_url),
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    def insert(self, record: RawFileRecord) -> RawFileRecord:
        """Insert an acquisition row and return it with database id."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
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
                """,
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
            record_id = cursor.lastrowid
        return RawFileRecord(
            id=record_id, **{k: v for k, v in vars(record).items() if k != "id"}
        )

    def touch_checked(self, record_id: int, checked_at: str) -> None:
        """Update last_checked_at for a cache-hit row."""
        with self._connect() as conn:
            conn.execute(
                """
                update raw_file_acquisitions
                set last_checked_at = ?
                where id = ?
                """,
                (checked_at, record_id),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma busy_timeout = 5000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
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
                """
            )
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


def _record_from_row(row: sqlite3.Row) -> RawFileRecord:
    values: dict[str, Any] = dict(row)
    return RawFileRecord(**values)
