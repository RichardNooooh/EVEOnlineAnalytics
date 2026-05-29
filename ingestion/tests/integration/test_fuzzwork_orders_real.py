from __future__ import annotations

from pathlib import Path
import gzip

import duckdb
import pytest

from ingest.publishers.ducklake import DuckLakeAttachConfig, DuckLakeWriter, RawDuckLakeTable
from ingest.sources.everef.fuzzwork_orders import _process_result
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
    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)
    monkeypatch.setattr("ingest.publishers.ducklake._attach_ducklake", lambda c, config: None)
    yield con._con
    con._con.close()


_ATTACH = DuckLakeAttachConfig(
    attach_uri=":memory:",
    data_path="",
    metadata_schema="memory",
    alias="memory",
)


def _write_orderset_file(path: Path, price: float) -> None:
    path.write_bytes(
        gzip.compress(
            (f"1\t34\t2026-01-01T00:00:00Z\tTrue\t10\t100\t1\t{price}\t60000001\t0\t30\t10000002\t161676\n").encode()
        )
    )


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_process_result_merges_fuzzwork_orders_rows(shared_con, tmp_path: Path) -> None:
    first_path = tmp_path / "fuzzwork-a.csv.gz"
    second_path = tmp_path / "fuzzwork-b.csv.gz"
    _write_orderset_file(first_path, price=9.99)
    _write_orderset_file(second_path, price=99.99)

    identity_key = {"source_date": "2026-01-01", "order_set_id": "161676", "snapshot_time": "2026-01-01_00-00-00"}
    first = make_cache_result(
        str(first_path),
        content_length=first_path.stat().st_size,
        last_modified="2026-01-01T12:06:49Z",
        dataset_name="fuzzwork-orders",
        identity_key=identity_key,
        source_url="https://data.everef.net/fuzzwork/ordersets/2026/2026-01-01/fuzzwork-orderset-161676-2026-01-01_00-00-00.csv.gz",
    )
    second = make_cache_result(
        str(second_path),
        content_length=second_path.stat().st_size,
        last_modified="2026-01-01T12:06:49Z",
        dataset_name="fuzzwork-orders",
        identity_key=identity_key,
        source_url="https://data.everef.net/fuzzwork/ordersets/2026/2026-01-01/fuzzwork-orderset-161676-2026-01-01_00-00-00.csv.gz",
    )

    with DuckLakeWriter(_ATTACH) as writer:
        assert _process_result(first, writer) is True

    with DuckLakeWriter(_ATTACH) as writer:
        assert _process_result(second, writer) is True

    rows = shared_con.execute(
        f'SELECT order_id, price, order_set_id, snapshot_time FROM "memory"."raw"."{RawDuckLakeTable.FUZZWORK_ORDERS.value}" ORDER BY order_id'
    ).fetchall()

    assert rows == [(1, 9.99, 161676, "2026-01-01_00-00-00")]
