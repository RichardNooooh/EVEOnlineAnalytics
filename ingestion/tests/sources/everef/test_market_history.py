from __future__ import annotations

import bz2
import logging
import pathlib
from datetime import date

import pytest

from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.raw_objects import UpdateMode
from eve_ingest.sources.everef.market_history import PUBLISHER_SPEC, _build_cache_objects
from eve_ingest.sources.everef.csv_reader import parse_csv_to_arrow
from tests.sources.everef.conftest import make_cache_result

_ORIGINAL_COLS = [
    "average",
    "date",
    "highest",
    "lowest",
    "order_count",
    "volume",
    "http_last_modified",
    "region_id",
    "type_id",
]


def test_publisher_spec_declares_market_history_mutations() -> None:
    assert PUBLISHER_SPEC.dataset_name == "market-history"
    assert PUBLISHER_SPEC.update_mode is UpdateMode.MUTABLE
    assert PUBLISHER_SPEC.data_tables == (RawDuckLakeTable.MARKET_HISTORY,)
    assert PUBLISHER_SPEC.provenance_tables == (RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS,)
    assert PUBLISHER_SPEC.writer_mode is DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS
    assert PUBLISHER_SPEC.publication_scope({"source_date": "2026-01-01"}) == (
        "raw:market_history:source_date=2026-01-01"
    )


class TestBuildCacheObjects:
    def test_dates_and_urls(self) -> None:
        objects = _build_cache_objects(date(2026, 1, 1), date(2026, 1, 3))

        assert len(objects) == 3

        assert objects[0].source_url == (
            "https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2"
        )
        assert objects[0].identity_key == {"source_date": "2026-01-01"}

        assert objects[1].source_url == (
            "https://data.everef.net/market-history/2026/market-history-2026-01-02.csv.bz2"
        )
        assert objects[1].identity_key == {"source_date": "2026-01-02"}

        assert objects[2].source_url == (
            "https://data.everef.net/market-history/2026/market-history-2026-01-03.csv.bz2"
        )
        assert objects[2].identity_key == {"source_date": "2026-01-03"}

    def test_single_date(self) -> None:
        objects = _build_cache_objects(date(2026, 6, 15), date(2026, 6, 15))

        assert len(objects) == 1
        assert objects[0].source_url == (
            "https://data.everef.net/market-history/2026/market-history-2026-06-15.csv.bz2"
        )
        assert objects[0].identity_key == {"source_date": "2026-06-15"}

    def test_logs_daily_archive_queue(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("eve_ingest.sources.everef")
        logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.INFO, logger=logger.name):
                _build_cache_objects(date(2026, 1, 1), date(2026, 1, 2))
        finally:
            logger.removeHandler(caplog.handler)

        assert "Queued daily archive source_date=2026-01-01" in caplog.text
        assert "Queued daily archive source_date=2026-01-02" in caplog.text


class TestParseCsvToArrow:
    CSV_CONTENT = (
        "average,date,highest,lowest,order_count,volume,"
        "http_last_modified,region_id,type_id\n"
        "9.99,2026-01-01,9.99,9.99,1,24,"
        "2026-01-02T11:01:55Z,10000001,19\n"
    )

    @pytest.fixture
    def csv_path(self, tmp_path: pathlib.Path) -> pathlib.Path:
        path = tmp_path / "market-history-2026-01-01.csv.bz2"
        with bz2.open(path, "wt") as f:
            f.write(self.CSV_CONTENT)
        return path

    def test_parses_without_provenance(self, csv_path: pathlib.Path) -> None:
        result = make_cache_result(
            str(csv_path),
            content_length=csv_path.stat().st_size,
            last_modified="2026-01-02T11:01:55Z",
            source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
        )
        table = parse_csv_to_arrow(result)

        for col in _ORIGINAL_COLS:
            assert col in table.column_names, f"missing column: {col}"

        assert len(table) == 1
        assert table.column("average")[0].as_py() == 9.99
        assert table.column("region_id")[0].as_py() == 10000001
        assert table.column("type_id")[0].as_py() == 19

        # Verify no provenance columns were added
        for col in table.column_names:
            assert not col.startswith("_source"), f"Unexpected provenance column: {col}"
        assert "_ingested_at" not in table.column_names

    def test_handles_missing_last_modified(self, csv_path: pathlib.Path) -> None:
        result = make_cache_result(
            str(csv_path),
            last_modified=None,
            source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
        )
        table = parse_csv_to_arrow(result)

        # parse_csv_to_arrow does not add provenance columns
        assert "_source_last_modified" not in table.column_names
        assert "_source_content_length" not in table.column_names
        # Original columns are still present
        assert "average" in table.column_names
