from __future__ import annotations

from ingest.cache.ledger import RawObjectLedger
from ingest.cache.ledger import runtime as ledger_runtime


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
        assert tx._con is connection

    assert bootstrap_calls == 1
    assert engine.begin_calls == 1
    assert engine.disposed is False
    ledger.close()
    assert engine.disposed is True
    ledger.close()
