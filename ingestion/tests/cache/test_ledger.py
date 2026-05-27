from __future__ import annotations

from ingest.cache.ledger import RawObjectLedger


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.disposed = False

    def connect(self) -> FakeConnection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


def test_ledger_lifecycle(monkeypatch) -> None:
    connection = FakeConnection()
    engine = FakeEngine(connection)
    bootstrap_calls = 0

    monkeypatch.setattr("ingest.cache.ledger.create_engine", lambda url: engine)
    ledger = RawObjectLedger(ledger_url="postgresql://user:pass@host/db")

    def _bootstrap(self) -> None:
        nonlocal bootstrap_calls
        bootstrap_calls += 1

    monkeypatch.setattr(RawObjectLedger, "_bootstrap", _bootstrap)

    with ledger:
        assert ledger._engine is engine
        assert ledger._con is connection

    assert bootstrap_calls == 1
    assert connection.closed is True
    assert engine.disposed is True
    ledger.close()
    ledger.close()
