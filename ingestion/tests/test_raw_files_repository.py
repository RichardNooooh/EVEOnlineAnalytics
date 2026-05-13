from __future__ import annotations

from pathlib import Path
from typing import Any

from conftest import raw_file_record
import ingest.raw_files.repository as repository_module
from ingest.raw_files.config import sqlite_ledger_url
from ingest.raw_files.repository import RawFileRepository


def test_repository_insert_returns_record_with_id_and_persists_fields(
    tmp_path: Path,
) -> None:
    repository = RawFileRepository(
        sqlite_ledger_url(tmp_path / "raw" / "raw_files.sqlite")
    )
    inserted = repository.insert(raw_file_record())

    found = repository.find_latest_success(
        source_name="source",
        dataset_name="dataset",
        source_date="2025-01-01",
        source_url="https://example.test/file.csv.bz2",
    )

    assert inserted.id is not None
    assert found == inserted


def test_repository_find_latest_success_ignores_failed_rows(tmp_path: Path) -> None:
    repository = RawFileRepository(
        sqlite_ledger_url(tmp_path / "raw" / "raw_files.sqlite")
    )
    repository.insert(raw_file_record(status="failed", downloaded_at=None))
    success = repository.insert(raw_file_record(status="downloaded"))

    found = repository.find_latest_success(
        source_name="source",
        dataset_name="dataset",
        source_date="2025-01-01",
        source_url="https://example.test/file.csv.bz2",
    )

    assert found == success


def test_repository_find_latest_success_filters_identity(tmp_path: Path) -> None:
    repository = RawFileRepository(
        sqlite_ledger_url(tmp_path / "raw" / "raw_files.sqlite")
    )
    repository.insert(raw_file_record(source_name="other"))
    repository.insert(raw_file_record(dataset_name="other"))
    repository.insert(raw_file_record(source_date="2025-01-02"))
    repository.insert(raw_file_record(source_url="https://example.test/other.csv.bz2"))
    expected = repository.insert(raw_file_record())

    found = repository.find_latest_success(
        source_name="source",
        dataset_name="dataset",
        source_date="2025-01-01",
        source_url="https://example.test/file.csv.bz2",
    )

    assert found == expected


def test_repository_find_latest_success_returns_newest_downloaded_row(
    tmp_path: Path,
) -> None:
    repository = RawFileRepository(
        sqlite_ledger_url(tmp_path / "raw" / "raw_files.sqlite")
    )
    repository.insert(raw_file_record(downloaded_at="2025-01-01T00:00:00+00:00"))
    newest = repository.insert(
        raw_file_record(downloaded_at="2025-01-02T00:00:00+00:00")
    )
    tie_winner = repository.insert(
        raw_file_record(downloaded_at="2025-01-02T00:00:00+00:00")
    )

    found = repository.find_latest_success(
        source_name="source",
        dataset_name="dataset",
        source_date="2025-01-01",
        source_url="https://example.test/file.csv.bz2",
    )

    assert newest.id is not None
    assert found == tie_winner


def test_repository_list_successes_for_source_date_returns_newest_with_local_path(
    tmp_path: Path,
) -> None:
    repository = RawFileRepository(
        sqlite_ledger_url(tmp_path / "raw" / "raw_files.sqlite")
    )
    old = repository.insert(
        raw_file_record(
            local_path="/tmp/old", downloaded_at="2025-01-01T00:00:00+00:00"
        )
    )
    new = repository.insert(
        raw_file_record(
            local_path="/tmp/new", downloaded_at="2025-01-02T00:00:00+00:00"
        )
    )
    repository.insert(raw_file_record(local_path=None))
    repository.insert(raw_file_record(status="failed"))

    rows = repository.list_successes_for_source_date(
        source_name="source",
        dataset_name="dataset",
        source_date="2025-01-01",
    )

    assert rows == [new, old]


def test_repository_delete_successes_for_local_paths_removes_only_matching_downloaded(
    tmp_path: Path,
) -> None:
    repository = RawFileRepository(
        sqlite_ledger_url(tmp_path / "raw" / "raw_files.sqlite")
    )
    repository.insert(raw_file_record(local_path="/tmp/delete"))
    keep = repository.insert(raw_file_record(local_path="/tmp/keep"))
    repository.insert(raw_file_record(local_path="/tmp/delete", status="failed"))

    repository.delete_successes_for_local_paths({"/tmp/delete"})

    rows = repository.list_successes_for_source_date(
        source_name="source",
        dataset_name="dataset",
        source_date="2025-01-01",
    )

    assert rows == [keep]


def test_repository_delete_successes_for_local_paths_accepts_empty_set(
    tmp_path: Path,
) -> None:
    repository = RawFileRepository(
        sqlite_ledger_url(tmp_path / "raw" / "raw_files.sqlite")
    )
    keep = repository.insert(raw_file_record())

    repository.delete_successes_for_local_paths(set())

    rows = repository.list_successes_for_source_date(
        source_name="source",
        dataset_name="dataset",
        source_date="2025-01-01",
    )
    assert rows == [keep]


def test_repository_touch_checked_updates_one_row(tmp_path: Path) -> None:
    repository = RawFileRepository(
        sqlite_ledger_url(tmp_path / "raw" / "raw_files.sqlite")
    )
    target = repository.insert(raw_file_record(local_path="/tmp/target"))
    other = repository.insert(raw_file_record(local_path="/tmp/other"))
    assert target.id is not None

    repository.touch_checked(target.id, "2025-01-03T00:00:00+00:00")

    rows = repository.list_successes_for_source_date(
        source_name="source",
        dataset_name="dataset",
        source_date="2025-01-01",
    )
    by_path = {row.local_path: row for row in rows}
    assert by_path["/tmp/target"].last_checked_at == "2025-01-03T00:00:00+00:00"
    assert by_path["/tmp/other"].last_checked_at == other.last_checked_at


def test_repository_supports_postgres_dbapi(monkeypatch) -> None:
    connections: list[FakePostgresConnection] = []

    def connect(ledger_url: str) -> FakePostgresConnection:
        assert ledger_url == "postgresql://ledger.test/raw"
        connection = FakePostgresConnection()
        connections.append(connection)
        return connection

    monkeypatch.setattr(repository_module, "_connect_postgres", connect)

    repository = RawFileRepository("postgresql://ledger.test/raw")
    inserted = repository.insert(raw_file_record())

    assert inserted.id == 42
    statements = [sql for connection in connections for sql, _ in connection.calls]
    assert any("id bigserial primary key" in sql for sql in statements)
    insert_sql = next(
        sql for sql in statements if "insert into raw_file_acquisitions" in sql
    )
    assert "%s" in insert_sql
    assert "?" not in insert_sql
    assert "returning id" in insert_sql


class FakePostgresConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "FakePostgresConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> "FakePostgresCursor":
        self.calls.append((sql, params))
        return FakePostgresCursor(sql)


class FakePostgresCursor:
    description = (("id",),)
    lastrowid = None

    def __init__(self, sql: str) -> None:
        self.sql = sql

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> "FakePostgresCursor":
        return self

    def fetchone(self) -> tuple[int] | None:
        if "returning id" in self.sql:
            return (42,)
        return None

    def fetchall(self) -> list[Any]:
        return []
