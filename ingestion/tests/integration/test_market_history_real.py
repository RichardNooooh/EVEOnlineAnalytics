from __future__ import annotations

import bz2
from datetime import date
from pathlib import Path

import duckdb
import pytest

from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig
from eve_ingest.ducklake.locks import DuckLakeLockToken, ducklake_lock_domains_for_tables
from eve_ingest.ducklake.writer import DuckLakeWriter, bootstrap_raw_ducklake
from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.sources.everef.market_history import _process_result
from eve_ingest.sources.everef.csv_reader import parse_csv_to_arrow
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


def _write_history_file(path: Path) -> None:
    path.write_bytes(
        bz2.compress(
            (
                "average,date,highest,lowest,order_count,volume,http_last_modified,region_id,type_id\n"
                "9.99,2026-01-01,9.99,9.99,1,24,2026-01-02T11:01:55Z,10000001,19\n"
            ).encode()
        )
    )


@pytest.mark.real_duckdb
def test_process_result_writes_and_merges_history_rows(shared_con, tmp_path: Path) -> None:
    file_path = tmp_path / "market-history-2026-01-01.csv.bz2"
    _write_history_file(file_path)

    result = make_cache_result(
        str(file_path),
        content_length=file_path.stat().st_size,
        last_modified="2026-01-02T11:01:55Z",
        source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
    )

    table = parse_csv_to_arrow(result)
    assert "source_market_date" not in table.column_names
    assert "_source_market_date" not in table.column_names
    assert all(not c.startswith("_source") for c in table.column_names)

    with DuckLakeWriter(_ATTACH, lock_token=_test_lock_token()) as writer:
        first_outcome = _process_result(result, writer)
        assert first_outcome.success is True
        assert len(first_outcome.write_metrics) == 1
        assert first_outcome.write_metrics[0].inserted_rows == 1
        assert first_outcome.write_metrics[0].matched_rows == 0

    with DuckLakeWriter(_ATTACH, lock_token=_test_lock_token()) as writer:
        second_outcome = _process_result(result, writer)
        assert second_outcome.success is True
        assert len(second_outcome.write_metrics) == 1
        assert second_outcome.write_metrics[0].inserted_rows == 0
        assert second_outcome.write_metrics[0].matched_rows == 1

    rows = shared_con.execute(
        f'SELECT average, "date", region_id, type_id FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}"'
    ).fetchall()

    assert rows == [(9.99, date(2026, 1, 1), 10000001, 19)]
