from __future__ import annotations

import pytest

from eve_ingest.ducklake.locks import (
    DUCKLAKE_MAINTENANCE_LOCK_DOMAIN,
    DUCKLAKE_MIGRATION_LOCK_DOMAIN,
    DuckLakeLockContext,
    DuckLakeLockTimeoutError,
    ducklake_lock_domains_for_publication_scope,
    ducklake_lock_key,
    hold_ducklake_lock_domains,
    ordered_ducklake_lock_domains,
)


class _FakeCursor:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params=None) -> None:
        self.connection.calls.append((query, params))
        if self.connection.raise_on_lock and query.startswith("select pg_advisory_lock"):
            raise self.connection.raise_on_lock


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.closed = False
        self.raise_on_lock: Exception | None = None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def test_lock_domains_follow_fixed_rank_order() -> None:
    ordered = ordered_ducklake_lock_domains(
        (
            "ducklake:support:raw_market_orders_objects",
            "ducklake:raw:raw_market_orders",
            DUCKLAKE_MAINTENANCE_LOCK_DOMAIN,
            DUCKLAKE_MIGRATION_LOCK_DOMAIN,
        )
    )

    assert ordered == (
        DUCKLAKE_MIGRATION_LOCK_DOMAIN,
        DUCKLAKE_MAINTENANCE_LOCK_DOMAIN,
        "ducklake:raw:raw_market_orders",
        "ducklake:support:raw_market_orders_objects",
    )


def test_lock_domains_deduplicate_without_changing_rank_order() -> None:
    ordered = ordered_ducklake_lock_domains(
        (
            "ducklake:support:raw_market_orders_objects",
            "ducklake:raw:raw_market_orders",
            "ducklake:raw:raw_market_orders",
            DUCKLAKE_MAINTENANCE_LOCK_DOMAIN,
            "ducklake:support:raw_market_orders_objects",
        )
    )

    assert ordered == (
        DUCKLAKE_MAINTENANCE_LOCK_DOMAIN,
        "ducklake:raw:raw_market_orders",
        "ducklake:support:raw_market_orders_objects",
    )


def test_publication_scope_maps_to_data_and_support_domains() -> None:
    assert ducklake_lock_domains_for_publication_scope("raw:market_history:source_date=2026-01-01") == (
        "ducklake:raw:raw_market_history",
        "ducklake:support:raw_market_history_objects",
    )
    assert ducklake_lock_domains_for_publication_scope("raw:references:full_extract") == (
        "ducklake:raw:references",
        "ducklake:support:raw_reference_objects",
    )


def test_lock_key_is_stable() -> None:
    domain = "ducklake:raw:raw_market_orders"
    assert ducklake_lock_key(domain) == ducklake_lock_key(domain)


def test_hold_ducklake_lock_domains_sets_timeout_orders_domains_and_logs_context(monkeypatch, caplog) -> None:
    connection = _FakeConnection()
    monkeypatch.setattr("eve_ingest.ducklake.locks.psycopg.connect", lambda *args, **kwargs: connection)

    with caplog.at_level("INFO", logger="eve_ingest.ducklake"):
        with hold_ducklake_lock_domains(
            catalog_url="postgresql://user:pass@localhost:5432/db",
            lock_domains=("ducklake:support:raw_market_orders_objects", "ducklake:raw:raw_market_orders"),
            timeout_seconds=12.5,
            context=DuckLakeLockContext(
                dataset="market-history",
                publication_scope="raw:market_history:source_date=2026-01-01",
                table="raw_market_history",
                source_date="2026-01-01",
                airflow_run_id="airflow-run-123",
            ),
        ):
            pass

    assert connection.closed is True
    assert connection.calls[0] == ("select set_config('statement_timeout', %s, false)", ("12500",))
    lock_calls = [call for call in connection.calls if call[0].startswith("select pg_advisory_lock")]
    assert [call[1] for call in lock_calls] == [
        (ducklake_lock_key("ducklake:raw:raw_market_orders"),),
        (ducklake_lock_key("ducklake:support:raw_market_orders_objects"),),
    ]
    assert (
        "Waiting for DuckLake advisory locks domains=['ducklake:raw:raw_market_orders', 'ducklake:support:raw_market_orders_objects'] timeout_seconds=12.5 dataset=market-history publication_scope=raw:market_history:source_date=2026-01-01 table=raw_market_history source_date=2026-01-01 airflow_run_id=airflow-run-123"
        in caplog.text
    )
    assert (
        "Acquired DuckLake advisory lock domain=ducklake:raw:raw_market_orders dataset=market-history publication_scope=raw:market_history:source_date=2026-01-01 table=raw_market_history source_date=2026-01-01 airflow_run_id=airflow-run-123"
        in caplog.text
    )
    assert (
        "Releasing DuckLake advisory locks domains=['ducklake:raw:raw_market_orders', 'ducklake:support:raw_market_orders_objects'] dataset=market-history publication_scope=raw:market_history:source_date=2026-01-01 table=raw_market_history source_date=2026-01-01 airflow_run_id=airflow-run-123"
        in caplog.text
    )


def test_hold_ducklake_lock_domains_raises_timeout(monkeypatch) -> None:
    connection = _FakeConnection()
    connection.raise_on_lock = __import__("psycopg").errors.QueryCanceled()
    monkeypatch.setattr("eve_ingest.ducklake.locks.psycopg.connect", lambda *args, **kwargs: connection)

    with pytest.raises(DuckLakeLockTimeoutError, match="ducklake:raw:raw_market_orders"):
        with hold_ducklake_lock_domains(
            catalog_url="postgresql://user:pass@localhost:5432/db",
            lock_domains=("ducklake:raw:raw_market_orders",),
            timeout_seconds=0.1,
        ):
            pytest.fail("lock acquisition should have timed out")
