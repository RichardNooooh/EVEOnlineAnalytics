from __future__ import annotations

from pathlib import Path
import bz2

import duckdb
import pytest

from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig
from eve_ingest.ducklake.locks import DuckLakeLockToken, ducklake_lock_domains_for_tables
from eve_ingest.ducklake.writer import DuckLakeWriter, bootstrap_raw_ducklake
from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable
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
                "order_id,type_id,region_id,location_id,system_id,range,price,volume_remain,volume_total,min_volume,issued,expires,duration,is_buy_order,reported_by,http_last_modified\n"
                f"1,34,10000001,60000001,30000001,0,{price},10,100,1,2026-01-01T00:00:00Z,2026-02-01T00:00:00Z,30,True,1000001,2026-01-01T00:00:00Z\n"
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
    assert len(second_outcome.write_metrics) == 1
    assert second_outcome.write_metrics[0].inserted_rows == 0
    assert second_outcome.write_metrics[0].matched_rows == 1

    rows = shared_con.execute(
        f'SELECT order_id, price FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY price'
    ).fetchall()

    assert rows == [(1, 9.99)]
