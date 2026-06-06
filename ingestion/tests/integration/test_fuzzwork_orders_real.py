from __future__ import annotations

from pathlib import Path
import gzip

import duckdb
import pytest

from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig
from eve_ingest.ducklake.locks import DuckLakeLockToken, ducklake_lock_domains_for_tables
from eve_ingest.ducklake.writer import DuckLakeWriter, bootstrap_raw_ducklake
from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.sources.everef.fuzzwork_orders import _process_result
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


def _write_orderset_file(path: Path, price: float) -> None:
    path.write_bytes(
        gzip.compress(
            (f"1\t34\t2026-01-01T00:00:00Z\tTrue\t10\t100\t1\t{price}\t60000001\t0\t30\t10000002\t161676\n").encode()
        )
    )


@pytest.mark.real_duckdb
def test_process_result_is_idempotent_for_same_fuzzwork_orders_source_object(shared_con, tmp_path: Path) -> None:
    file_path = tmp_path / "fuzzwork.csv.gz"
    _write_orderset_file(file_path, price=9.99)

    result = make_cache_result(
        str(file_path),
        content_length=file_path.stat().st_size,
        last_modified="2026-01-01T12:06:49Z",
        dataset_name="fuzzwork-orders",
        identity_key={"source_date": "2026-01-01", "order_set_id": "161676", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://data.everef.net/fuzzwork/ordersets/2026/2026-01-01/fuzzwork-orderset-161676-2026-01-01_00-00-00.csv.gz",
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
        f'SELECT order_id, price FROM "memory"."raw"."{RawDuckLakeTable.FUZZWORK_ORDERS.value}" ORDER BY price'
    ).fetchall()

    assert rows == [(1, 9.99)]
