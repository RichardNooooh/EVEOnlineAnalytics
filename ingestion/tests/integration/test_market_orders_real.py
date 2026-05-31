from __future__ import annotations

from pathlib import Path
import bz2

import duckdb
import pytest

from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig
from eve_ingest.ducklake.writer import DuckLakeWriter
from eve_ingest.ducklake.raw_tables import RawDuckLakeTable
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
    monkeypatch.setattr("eve_ingest.ducklake.writer._attach_ducklake", lambda c, config: None)
    yield con._con
    con._con.close()


_ATTACH = DuckLakeAttachConfig(
    attach_uri=":memory:",
    data_path="",
    metadata_schema="memory",
    alias="memory",
)


def _write_orders_file(path: Path, price: float) -> None:
    path.write_bytes(
        bz2.compress(
            (
                "order_id,type_id,region_id,location_id,system_id,range,price,volume_remain,volume_total,min_volume,issued,expires,duration,is_buy_order,reported_by,http_last_modified\n"
                f"1,34,10000001,60000001,30000001,0,{price},10,100,1,2026-01-01T00:00:00Z,2026-02-01T00:00:00Z,30,True,1000001,2026-01-01T00:00:00Z\n"
            ).encode()
        )
    )


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_process_result_merges_market_orders_rows(shared_con, tmp_path: Path) -> None:
    first_path = tmp_path / "market-orders-a.csv.bz2"
    second_path = tmp_path / "market-orders-b.csv.bz2"
    _write_orders_file(first_path, price=9.99)
    _write_orders_file(second_path, price=99.99)

    first = make_cache_result(
        str(first_path),
        content_length=first_path.stat().st_size,
        last_modified="2026-01-01T00:00:00Z",
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/market-orders-a.csv.bz2",
    )
    second = make_cache_result(
        str(second_path),
        content_length=second_path.stat().st_size,
        last_modified="2026-01-01T00:00:00Z",
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/market-orders-b.csv.bz2",
    )

    with DuckLakeWriter(_ATTACH) as writer:
        first_outcome = _process_result(first, writer)

    assert first_outcome.success is True
    assert first_outcome.source_date == "2026-01-01"
    assert len(first_outcome.write_metrics) == 1
    assert first_outcome.write_metrics[0].inserted_rows == 1
    assert first_outcome.write_metrics[0].matched_rows == 0

    with DuckLakeWriter(_ATTACH) as writer:
        second_outcome = _process_result(second, writer)

    assert second_outcome.success is True
    assert second_outcome.source_date == "2026-01-01"
    assert len(second_outcome.write_metrics) == 1
    assert second_outcome.write_metrics[0].inserted_rows == 1
    assert second_outcome.write_metrics[0].matched_rows == 0

    rows = shared_con.execute(
        f'SELECT order_id, price FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}" ORDER BY price'
    ).fetchall()

    assert len(rows) == 2
    assert rows[0] == (1, 9.99)
    assert rows[1] == (1, 99.99)
