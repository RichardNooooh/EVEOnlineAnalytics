"""Tests for DuckLake advisory lock acquisition, domain ordering, and token lifecycle."""

from __future__ import annotations

import logging

import pytest
from eve_ingest.ducklake.locks import (
    DUCKLAKE_MIGRATION_LOCK_DOMAIN,
    DuckLakeLockContext,
    DuckLakeLockTimeoutError,
    DuckLakeLockToken,
    all_raw_publication_lock_domains,
    ducklake_lock_domains_for_publication_scope,
    ducklake_lock_domains_for_tables,
    ducklake_lock_key,
    hold_ducklake_lock_domains,
    ordered_ducklake_lock_domains,
    provenance_table_lock_domain,
    raw_bootstrap_lock_domains,
    raw_table_lock_domain,
)
from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable


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

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def test_lock_domains_follow_fixed_rank_order() -> None:
    ordered = ordered_ducklake_lock_domains(
        (
            "ducklake:support:raw_market_orders_objects",
            "ducklake:raw:raw_market_orders",
            DUCKLAKE_MIGRATION_LOCK_DOMAIN,
        )
    )

    assert ordered == (
        DUCKLAKE_MIGRATION_LOCK_DOMAIN,
        "ducklake:raw:raw_market_orders",
        "ducklake:support:raw_market_orders_objects",
    )


def test_lock_domains_deduplicate_without_changing_rank_order() -> None:
    ordered = ordered_ducklake_lock_domains(
        (
            "ducklake:support:raw_market_orders_objects",
            "ducklake:raw:raw_market_orders",
            "ducklake:raw:raw_market_orders",
            "ducklake:support:raw_market_orders_objects",
        )
    )

    assert ordered == (
        "ducklake:raw:raw_market_orders",
        "ducklake:support:raw_market_orders_objects",
    )


def test_publication_scope_maps_to_data_and_support_domains() -> None:
    assert ducklake_lock_domains_for_publication_scope("raw:market_history:source_date=2026-01-01") == (
        "ducklake:raw:raw_market_history",
        "ducklake:support:raw_market_history_objects",
    )
    assert ducklake_lock_domains_for_publication_scope("raw:market_orders:source_date=2026-01-01") == (
        "ducklake:raw:raw_market_orders",
        "ducklake:support:raw_market_orders_objects",
    )
    assert ducklake_lock_domains_for_publication_scope("raw:fuzzwork_orders:source_date=2026-01-01") == (
        "ducklake:raw:raw_fuzzwork_orders",
        "ducklake:support:raw_fuzzwork_orders_objects",
    )
    assert ducklake_lock_domains_for_publication_scope("raw:references:full_extract") == (
        "ducklake:raw:raw_reference_categories",
        "ducklake:raw:raw_reference_groups",
        "ducklake:raw:raw_reference_market_groups",
        "ducklake:raw:raw_reference_regions",
        "ducklake:raw:raw_reference_types",
        "ducklake:support:raw_reference_objects",
    )


def test_table_lock_domains_are_derived_from_physical_tables() -> None:
    for table in RawDuckLakeTable:
        assert raw_table_lock_domain(table) == f"ducklake:raw:{table.value}"
    for table in RawDuckLakeProvenanceTable:
        assert provenance_table_lock_domain(table) == f"ducklake:support:{table.value}"


def test_ducklake_lock_domains_for_tables_orders_data_before_support() -> None:
    assert ducklake_lock_domains_for_tables(
        data_tables=(RawDuckLakeTable.MARKET_ORDERS,),
        provenance_tables=(RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,),
    ) == (
        "ducklake:raw:raw_market_orders",
        "ducklake:support:raw_market_orders_objects",
    )


def test_all_raw_publication_domains_include_every_raw_and_support_domain() -> None:
    domains = all_raw_publication_lock_domains()

    assert DUCKLAKE_MIGRATION_LOCK_DOMAIN not in domains
    for table in RawDuckLakeTable:
        assert raw_table_lock_domain(table) in domains
    for table in RawDuckLakeProvenanceTable:
        assert provenance_table_lock_domain(table) in domains


def test_raw_bootstrap_domains_include_migration_and_all_publication_domains() -> None:
    assert raw_bootstrap_lock_domains() == ordered_ducklake_lock_domains(
        (DUCKLAKE_MIGRATION_LOCK_DOMAIN, *all_raw_publication_lock_domains())
    )


def test_lock_key_is_stable() -> None:
    assert ducklake_lock_key("ducklake:raw:raw_market_orders") == -8572494044246768565


def test_lock_token_cannot_be_constructed_directly() -> None:
    with pytest.raises(TypeError, match="cannot be constructed directly"):
        DuckLakeLockToken(("ducklake:raw:raw_market_orders",))


def test_hold_ducklake_lock_domains_sets_timeout_orders_domains_and_logs_context(monkeypatch, caplog) -> None:
    connection = _FakeConnection()
    monkeypatch.setattr("eve_ingest.ducklake.locks.psycopg.connect", lambda *args, **kwargs: connection)

    token = None
    duck_logger = logging.getLogger("eve_ingest.ducklake")
    duck_logger.addHandler(caplog.handler)
    try:
        with (
            caplog.at_level("INFO", logger="eve_ingest.ducklake"),
            hold_ducklake_lock_domains(
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
            ) as token,
        ):
            assert isinstance(token, DuckLakeLockToken)
            assert token.is_active is True
            assert token.held_domains == (
                "ducklake:raw:raw_market_orders",
                "ducklake:support:raw_market_orders_objects",
            )
    finally:
        duck_logger.removeHandler(caplog.handler)

    assert token is not None
    assert token.is_active is False
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


def test_hold_ducklake_lock_domains_no_domain_token_is_only_active_inside_context() -> None:
    with hold_ducklake_lock_domains(
        catalog_url="postgresql://user:pass@localhost:5432/db",
        lock_domains=(),
        timeout_seconds=0.1,
    ) as token:
        assert token.held_domains == ()
        assert token.is_active is True

    assert token.is_active is False


def test_hold_ducklake_lock_domains_raises_timeout(monkeypatch) -> None:
    connection = _FakeConnection()
    connection.raise_on_lock = __import__("psycopg").errors.QueryCanceled()
    monkeypatch.setattr("eve_ingest.ducklake.locks.psycopg.connect", lambda *args, **kwargs: connection)

    with (
        pytest.raises(DuckLakeLockTimeoutError, match="ducklake:raw:raw_market_orders"),
        hold_ducklake_lock_domains(
            catalog_url="postgresql://user:pass@localhost:5432/db",
            lock_domains=("ducklake:raw:raw_market_orders",),
            timeout_seconds=0.1,
        ),
    ):
        pytest.fail("lock acquisition should have timed out")
