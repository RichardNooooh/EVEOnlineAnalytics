from __future__ import annotations

import bz2
import logging
import pathlib
from datetime import UTC, date, datetime

import pytest

from ingest.sources.everef.market_history import _build_cache_objects
from ingest.sources.everef.util import read_csv_to_arrow
from tests.sources.everef.conftest import make_cache_result

_PROVENANCE_COLS = [
    "_source_market_date",
    "_source_url",
    "_source_local_path",
    "_source_sha256",
    "_source_content_length",
    "_source_last_modified",
    "_source_downloaded_at",
    "_ingested_at",
]

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
        logger = logging.getLogger("ingest.sources.everef")
        logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.INFO, logger=logger.name):
                _build_cache_objects(date(2026, 1, 1), date(2026, 1, 2))
        finally:
            logger.removeHandler(caplog.handler)

        assert "Queued daily archive source_date=2026-01-01" in caplog.text
        assert "Queued daily archive source_date=2026-01-02" in caplog.text


class TestReadCsvToArrow:
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

    def test_adds_provenance(self, csv_path: pathlib.Path) -> None:
        result = make_cache_result(
            str(csv_path),
            content_length=csv_path.stat().st_size,
            last_modified="2026-01-02T11:01:55Z",
            source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
        )
        table = read_csv_to_arrow(result)

        for col in _ORIGINAL_COLS + _PROVENANCE_COLS:
            assert col in table.column_names, f"missing column: {col}"

        assert len(table) == 1
        assert table.column("_source_market_date")[0].as_py() == "2026-01-01"
        assert table.column("_source_local_path")[0].as_py() == str(csv_path)
        assert table.column("_source_url")[0].as_py() == (
            "https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2"
        )
        assert table.column("_source_sha256")[0].as_py() == "abc123"
        assert table.column("_source_downloaded_at")[0].as_py() == datetime(2026, 1, 2, 11, 1, 55, tzinfo=UTC)
        assert table.column("_source_content_length")[0].as_py() == csv_path.stat().st_size
        assert table.column("_source_last_modified")[0].as_py() == "2026-01-02T11:01:55Z"
        assert table.column("_ingested_at")[0].as_py() is not None
        assert isinstance(table.column("_source_downloaded_at")[0].as_py(), datetime)
        assert isinstance(table.column("_ingested_at")[0].as_py(), datetime)
        assert table.column("average")[0].as_py() == 9.99
        assert table.column("region_id")[0].as_py() == 10000001
        assert table.column("type_id")[0].as_py() == 19

    def test_handles_missing_last_modified(self, csv_path: pathlib.Path) -> None:
        result = make_cache_result(
            str(csv_path),
            last_modified=None,
            source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
        )
        table = read_csv_to_arrow(result)

        assert "_source_last_modified" in table.column_names
        assert "_source_content_length" in table.column_names
        assert table.column("_source_last_modified")[0].as_py() is None
        assert table.column("_source_content_length")[0].as_py() == csv_path.stat().st_size
