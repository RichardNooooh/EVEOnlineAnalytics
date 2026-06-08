from __future__ import annotations

from datetime import UTC
from pathlib import Path
import bz2

import duckdb
import pytest

from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig
from eve_ingest.ducklake.locks import DuckLakeLockToken, ducklake_lock_domains_for_tables
from eve_ingest.ducklake.writer import DuckLakeWriter, bootstrap_raw_ducklake
from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable, compute_source_object_id
from eve_ingest.sources.everef.market_orders import _process_result
from tests.sources.everef.conftest import make_cache_result


class _KeepConnection:
    def __init__(self) -> None:
        self._con = duckdb.connect(":memory:")

    def __getattr__(self, name: str):
        return getattr(self._con, name)

    def close(self) -> None:
        pass


@pytest.fixture
def shared_con(monkeypatch):
    con = _KeepConnection()
    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)
    monkeypatch.setattr("eve_ingest.ducklake.writer._attach", lambda c, config: None)
    yield con._con
    con._con.close()


_ATTACH = DuckLakeAttachConfig(
    attach_uri=":memory:",
    data_path="",
    metadata_schema="memory",
    alias="memory",
)


def _test_lock_token() -> DuckLakeLockToken:
    return DuckLakeLockToken.unsafe_for_tests(
        ducklake_lock_domains_for_tables(
            data_tables=tuple(RawDuckLakeTable),
            provenance_tables=tuple(RawDuckLakeProvenanceTable),
        )
    )


@pytest.fixture(autouse=True)
def bootstrapped(shared_con) -> None:
    bootstrap_raw_ducklake(_ATTACH)


def _write_orders_file(path: Path, price: float) -> None:
    path.write_bytes(
        bz2.compress(
            (
                "duration,is_buy_order,issued,location_id,min_volume,order_id,price,range,system_id,type_id,volume_remain,volume_total,http_last_modified,station_id,region_id,constellation_id\n"
                f"30,True,2026-01-01T00:00:00Z,60000001,1,1,{price},0,30000001,34,10,100,2026-01-01T00:00:00Z,60000001,10000001,20000001\n"
            ).encode()
        )
    )


@pytest.mark.real_duckdb
def test_process_result_is_idempotent_for_same_market_orders_source_object(shared_con, tmp_path: Path) -> None:
    file_path = tmp_path / "market-orders.csv.bz2"
    _write_orders_file(file_path, price=9.99)

    result = make_cache_result(
        str(file_path),
        content_length=file_path.stat().st_size,
        last_modified="2026-01-01T00:00:00Z",
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/market-orders.csv.bz2",
    )

    with DuckLakeWriter(_ATTACH, lock_token=_test_lock_token()) as writer:
        first_outcome = _process_result(result, writer)

    assert first_outcome.success is True
    assert first_outcome.source_date == "2026-01-01"
    assert len(first_outcome.write_metrics) == 1
    assert first_outcome.write_metrics[0].inserted_rows == 1
    assert first_outcome.write_metrics[0].matched_rows == 0

    with DuckLakeWriter(_ATTACH, lock_token=_test_lock_token()) as writer:
        second_outcome = _process_result(result, writer)

    assert second_outcome.success is True
    assert second_outcome.source_date == "2026-01-01"
    assert second_outcome.write_metrics == ()

    rows = shared_con.execute(
        f'SELECT order_id, price FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY price'
    ).fetchall()

    assert rows == [(1, 9.99)]


@pytest.mark.real_duckdb
def test_process_result_writes_native_metadata_and_provenance(shared_con, tmp_path: Path) -> None:
    file_path = tmp_path / "market-orders.csv.bz2"
    _write_orders_file(file_path, price=12.34)

    result = make_cache_result(
        str(file_path),
        content_length=file_path.stat().st_size,
        last_modified="2026-01-01T00:00:00Z",
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/market-orders.csv.bz2",
    )

    with DuckLakeWriter(_ATTACH, lock_token=_test_lock_token()) as writer:
        outcome = _process_result(result, writer)

    assert outcome.success is True
    expected_source_object_id = compute_source_object_id("everef", "market_orders", result.version.source_url)

    raw_rows = shared_con.execute(
        f'''SELECT order_id, price, source_object_id, source_market_date, snapshot_ts
        FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}"'''
    ).fetchall()
    assert len(raw_rows) == 1
    order_id, price, source_object_id, source_market_date, snapshot_ts = raw_rows[0]
    assert order_id == 1
    assert price == 12.34
    assert source_object_id == expected_source_object_id
    assert str(source_market_date) == "2026-01-01"
    assert snapshot_ts.astimezone(UTC).isoformat() == "2026-01-01T00:00:00+00:00"

    provenance_rows = shared_con.execute(
        f'''SELECT source_object_id, status, source_market_date, snapshot_ts
        FROM "memory"."raw"."{RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS.value}"'''
    ).fetchall()
    assert len(provenance_rows) == 1
    provenance_source_object_id, status, provenance_source_market_date, provenance_snapshot_ts = provenance_rows[0]
    assert provenance_source_object_id == expected_source_object_id
    assert status == "ingested"
    assert provenance_source_market_date == source_market_date
    assert provenance_snapshot_ts.astimezone(UTC).isoformat() == "2026-01-01T00:00:00+00:00"
