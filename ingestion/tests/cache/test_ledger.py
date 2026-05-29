from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, select

from ingest.cache.ledger import RawObjectLedger
from ingest.cache.ledger import _db as ledger_db
from ingest.cache.ledger import runtime as ledger_runtime
from ingest.cache.ledger.publishing_tx import PublicationTrackerTx
from ingest.cache.ledger.reader import RawObjectReader
from ingest.cache.ledger.runtime import LedgerTx
from ingest.cache.ledger.schema import raw_objects, raw_object_versions
from ingest.cache.ledger.writer import RawObjectWriter
from ingest.cache.client_types import RevalidationMetadata
from ingest.cache.ledger.types import RawObjectRef
from ingest.cache.primitives import UpdateMode


class FakeBegin:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.executed = []

    def execute(self, statement) -> None:
        self.executed.append(statement)


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.disposed = False
        self.begin_calls = 0

    def begin(self) -> FakeBegin:
        self.begin_calls += 1
        return FakeBegin(self.connection)

    def dispose(self) -> None:
        self.disposed = True


def test_ledger_lifecycle(monkeypatch) -> None:
    connection = FakeConnection()
    engine = FakeEngine(connection)
    bootstrap_calls = 0

    monkeypatch.setattr(ledger_runtime, "create_engine", lambda url: engine)
    ledger = RawObjectLedger(ledger_url="postgresql://user:pass@host/db")

    def _bootstrap(self) -> None:
        nonlocal bootstrap_calls
        bootstrap_calls += 1
        self._bootstrapped = True

    monkeypatch.setattr(RawObjectLedger, "_bootstrap", _bootstrap)

    with ledger.transaction() as tx:
        assert ledger._engine is engine
        assert isinstance(tx, LedgerTx)
        assert isinstance(tx.reader, RawObjectReader)
        assert isinstance(tx.writer, RawObjectWriter)
        assert isinstance(tx.publications, PublicationTrackerTx)

    assert bootstrap_calls == 1
    assert engine.begin_calls == 1
    assert engine.disposed is False
    ledger.close()
    assert engine.disposed is True
    ledger.close()


def _make_ledger(monkeypatch) -> RawObjectLedger:
    """Return a ``RawObjectLedger`` backed by a real SQLite in-memory DB."""
    monkeypatch.setattr(
        ledger_runtime, "create_engine", lambda _: __import__("sqlalchemy").create_engine("sqlite:///:memory:")
    )
    monkeypatch.setattr(ledger_runtime, "normalize_ledger_url", lambda u: u)
    ledger = RawObjectLedger(ledger_url="sqlite:///:memory:")
    ledger._bootstrap()
    return ledger


def _seed_raw_object(con, *, raw_object_id: str, fetched_at: datetime, identity_hash: str = "hash-1") -> None:
    con.execute(
        insert(raw_objects).values(
            id=raw_object_id,
            source_name="everef",
            dataset_name="market-history",
            identity_key={"source_date": "2026-01-01"},
            identity_hash=identity_hash,
            update_mode="mutable",
            created_at=fetched_at,
            last_checked_at=fetched_at,
            etag=None,
            last_modified=None,
            content_length=None,
        )
    )


def _insert_version(
    con, *, version_id: str, raw_object_id: str, fetched_at: datetime, sha256: str = "abc", version_number: int = 0
) -> None:
    con.execute(
        insert(raw_object_versions).values(
            id=version_id,
            raw_object_id=raw_object_id,
            source_url="https://example.com/file.csv",
            fetched_at=fetched_at,
            etag=None,
            last_modified=None,
            content_length=None,
            sha256=sha256,
            local_path="/tmp/file.csv",
            storage_encoding="csv",
            version_number=version_number,
        )
    )


def test_rotate_version_rolls_back_on_insert_failure(monkeypatch) -> None:
    ledger = _make_ledger(monkeypatch)
    with ledger._engine.begin() as con:
        _seed_raw_object(con, raw_object_id="obj-1", fetched_at=datetime(2026, 1, 1, tzinfo=UTC))
        _insert_version(
            con,
            version_id="v-old",
            raw_object_id="obj-1",
            fetched_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            sha256="old",
            version_number=0,
        )

    def flaky_execute(con, statement):
        if "INSERT" in str(statement):
            raise RuntimeError("boom")
        return ledger_db._execute(con, statement)

    monkeypatch.setattr("ingest.cache.ledger.writer._execute", flaky_execute)

    with pytest.raises(RuntimeError, match="boom"):
        with ledger.transaction() as tx:
            tx.writer.rotate_version(
                ref=RawObjectRef(
                    source_name="everef",
                    dataset_name="market-history",
                    identity_hash="hash-1",
                    identity_key={"source_date": "2026-01-01"},
                    update_mode=UpdateMode.MUTABLE,
                ),
                source_url="https://example.com/file.csv",
                fetched_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                revalidation=RevalidationMetadata(),
                sha256="new",
                local_path="/tmp/file.csv",
                storage_encoding="csv",
            )

    with ledger._engine.begin() as con:
        rows = ledger_db._fetchall(
            con, select(raw_object_versions).where(raw_object_versions.c.raw_object_id == "obj-1")
        )
    assert len(rows) == 1
    assert rows[0]["id"] == "v-old"
