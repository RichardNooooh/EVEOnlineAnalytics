from __future__ import annotations

from pathlib import Path
from threading import Barrier, Thread
from time import sleep
from uuid import uuid4

import duckdb
import pytest

from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig, build_ducklake_attach_config_from_url
from eve_ingest.ducklake.locks import (
    DuckLakeLockTimeoutError,
    ducklake_lock_domains_for_publication_scope,
    hold_ducklake_lock_domains,
    raw_bootstrap_lock_domains,
)
from eve_ingest.ducklake.raw_tables import RawDuckLakeTable
from eve_ingest.ducklake.bootstrap import bootstrap_raw_ducklake
from eve_ingest.ducklake.session import DuckLakeSession
from eve_ingest.ducklake.sql import quote_identifier


@pytest.fixture
def attach_config(pg_url: str, tmp_path: Path) -> DuckLakeAttachConfig:
    suffix = uuid4().hex
    return build_ducklake_attach_config_from_url(
        pg_url,
        data_path=str(tmp_path / "ducklake"),
        metadata_schema=f"test_{suffix}",
        alias=f"ducklake_{suffix}",
    )


def _connect(attach_config: DuckLakeAttachConfig) -> duckdb.DuckDBPyConnection:
    session = DuckLakeSession(attach_config)
    session.__enter__()
    return session.connection


def _target(attach_config: DuckLakeAttachConfig, table: RawDuckLakeTable) -> str:
    return f"{quote_identifier(attach_config.alias)}.raw.{quote_identifier(table.value)}"


def _insert_market_order(
    con: duckdb.DuckDBPyConnection,
    attach_config: DuckLakeAttachConfig,
    *,
    order_id: int,
    price: float,
) -> None:
    con.execute(
        f"""
        INSERT INTO {_target(attach_config, RawDuckLakeTable.MARKET_ORDERS)}
            (order_id, price, source_market_date)
        VALUES (?, ?, DATE '2026-01-01')
        """,
        [order_id, price],
    )


def _insert_market_history(
    con: duckdb.DuckDBPyConnection,
    attach_config: DuckLakeAttachConfig,
    *,
    type_id: int,
    average: float,
) -> None:
    con.execute(
        f"""
        INSERT INTO {_target(attach_config, RawDuckLakeTable.MARKET_HISTORY)}
            (type_id, average, date, source_market_date)
        VALUES (?, ?, DATE '2026-01-01', DATE '2026-01-01')
        """,
        [type_id, average],
    )


@pytest.mark.integration
def test_separate_connections_can_commit_to_different_tables_concurrently(attach_config: DuckLakeAttachConfig) -> None:
    bootstrap_raw_ducklake(attach_config)

    start = Barrier(2)
    errors: list[BaseException] = []

    def publish_market_orders() -> None:
        con = _connect(attach_config)
        try:
            con.execute("BEGIN")
            start.wait(timeout=5)
            _insert_market_order(con, attach_config, order_id=1001, price=10.0)
            sleep(0.2)
            con.execute("COMMIT")
        except BaseException as exc:  # pragma: no cover - surfaced via assertion below
            errors.append(exc)
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
        finally:
            con.close()

    def publish_market_history() -> None:
        con = _connect(attach_config)
        try:
            con.execute("BEGIN")
            start.wait(timeout=5)
            _insert_market_history(con, attach_config, type_id=2002, average=20.0)
            sleep(0.2)
            con.execute("COMMIT")
        except BaseException as exc:  # pragma: no cover - surfaced via assertion below
            errors.append(exc)
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
        finally:
            con.close()

    order_thread = Thread(target=publish_market_orders)
    history_thread = Thread(target=publish_market_history)
    order_thread.start()
    history_thread.start()
    order_thread.join(timeout=10)
    history_thread.join(timeout=10)

    assert errors == []
    assert order_thread.is_alive() is False
    assert history_thread.is_alive() is False

    reader = _connect(attach_config)
    try:
        order_rows = reader.execute(
            f"SELECT order_id, price FROM {_target(attach_config, RawDuckLakeTable.MARKET_ORDERS)}"
        ).fetchall()
        history_rows = reader.execute(
            f"SELECT type_id, average FROM {_target(attach_config, RawDuckLakeTable.MARKET_HISTORY)}"
        ).fetchall()
    finally:
        reader.close()

    assert order_rows == [(1001, 10.0)]
    assert history_rows == [(2002, 20.0)]


@pytest.mark.integration
def test_reader_sees_only_committed_state_while_writer_transaction_is_open(attach_config: DuckLakeAttachConfig) -> None:
    bootstrap_raw_ducklake(attach_config)

    seed = _connect(attach_config)
    try:
        _insert_market_order(seed, attach_config, order_id=1, price=10.0)
    finally:
        seed.close()

    writer = _connect(attach_config)
    reader = _connect(attach_config)
    try:
        writer.execute("BEGIN")
        _insert_market_order(writer, attach_config, order_id=2, price=20.0)

        visible_before_commit = reader.execute(
            f"SELECT order_id FROM {_target(attach_config, RawDuckLakeTable.MARKET_ORDERS)} ORDER BY order_id"
        ).fetchall()
        assert visible_before_commit == [(1,)]

        writer.execute("COMMIT")

        visible_after_commit = reader.execute(
            f"SELECT order_id FROM {_target(attach_config, RawDuckLakeTable.MARKET_ORDERS)} ORDER BY order_id"
        ).fetchall()
        assert visible_after_commit == [(1,), (2,)]
    finally:
        writer.close()
        reader.close()


@pytest.mark.integration
def test_same_table_publication_scopes_serialize_on_shared_lock_domains(pg_url: str) -> None:
    first_scope = "raw:market_orders:source_date=2026-01-01"
    second_scope = "raw:market_orders:source_date=2026-01-02"

    with hold_ducklake_lock_domains(
        catalog_url=pg_url,
        lock_domains=ducklake_lock_domains_for_publication_scope(first_scope),
        timeout_seconds=5,
    ):
        with pytest.raises(DuckLakeLockTimeoutError, match="raw_market_orders"):
            with hold_ducklake_lock_domains(
                catalog_url=pg_url,
                lock_domains=ducklake_lock_domains_for_publication_scope(second_scope),
                timeout_seconds=0.1,
            ):
                pytest.fail("same-table publication scopes should serialize on shared lock domains")


@pytest.mark.integration
def test_different_table_publication_domains_can_overlap(pg_url: str) -> None:
    market_history_domains = ducklake_lock_domains_for_publication_scope("raw:market_history:source_date=2026-01-01")
    market_orders_domains = ducklake_lock_domains_for_publication_scope("raw:market_orders:source_date=2026-01-01")

    with hold_ducklake_lock_domains(
        catalog_url=pg_url,
        lock_domains=market_history_domains,
        timeout_seconds=5,
    ):
        with hold_ducklake_lock_domains(
            catalog_url=pg_url,
            lock_domains=market_orders_domains,
            timeout_seconds=0.1,
        ):
            pass


@pytest.mark.integration
def test_raw_bootstrap_lock_set_blocks_every_writer_domain(pg_url: str) -> None:
    writer_scopes = (
        "raw:market_history:source_date=2026-01-01",
        "raw:market_orders:source_date=2026-01-01",
        "raw:fuzzwork_orders:source_date=2026-01-01",
        "raw:references:full_extract",
    )

    with hold_ducklake_lock_domains(
        catalog_url=pg_url,
        lock_domains=raw_bootstrap_lock_domains(),
        timeout_seconds=5,
    ):
        for writer_scope in writer_scopes:
            with pytest.raises(DuckLakeLockTimeoutError):
                with hold_ducklake_lock_domains(
                    catalog_url=pg_url,
                    lock_domains=ducklake_lock_domains_for_publication_scope(writer_scope),
                    timeout_seconds=0.1,
                ):
                    pytest.fail(f"bootstrap lock set should block writer scope {writer_scope}")


def test_static_contract_rejects_legacy_raw_source_objects_references() -> None:
    ingestion_root = Path(__file__).resolve().parents[2] / "eve_ingest"
    offenders = sorted(
        str(path.relative_to(ingestion_root.parent))
        for path in ingestion_root.rglob("*.py")
        if "raw_source_objects" in path.read_text()
    )

    assert offenders == []
