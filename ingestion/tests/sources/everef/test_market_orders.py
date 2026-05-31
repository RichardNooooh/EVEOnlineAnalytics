from __future__ import annotations

import bz2
import logging
import pathlib
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import pyarrow as pa

from ingest.sources.everef.market_orders import (
    _SNAPSHOT_RE,
    _build_cache_objects,
    _process_result,
)
from ingest.sources.everef.util import list_snapshots, read_csv_to_arrow
from ingest.sources.everef import util as everef_util

from tests.sources.everef.conftest import make_cache_result

logger = logging.getLogger("ingest.sources.everef")


@pytest.fixture
def snapshot_html() -> str:
    return (
        '<html><body><a href="market-orders-2026-01-01_00-00-00.v3.csv.bz2">link1</a>'
        '<a href="market-orders-2026-01-01_12-00-00.v3.csv.bz2">link2</a></body></html>'
    )


@pytest.fixture
def real_listing_html() -> str:
    path = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "everef" / "market-orders-listing-2025-01-01.html"
    return path.read_text()


class TestListSnapshots:
    def test_extracts_filenames(self, snapshot_html: str) -> None:
        client = MagicMock()
        client.fetch_text.return_value = snapshot_html
        filenames = list_snapshots("market-orders/history", date(2026, 1, 1), _SNAPSHOT_RE, client)
        assert filenames == [
            "market-orders-2026-01-01_00-00-00.v3.csv.bz2",
            "market-orders-2026-01-01_12-00-00.v3.csv.bz2",
        ]

    def test_empty_html_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        client = MagicMock()
        client.fetch_text.return_value = "<html></html>"
        logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger=logger.name):
                filenames = list_snapshots("market-orders/history", date(2026, 1, 1), _SNAPSHOT_RE, client)
        finally:
            logger.removeHandler(caplog.handler)
        assert filenames == []
        assert "No snapshots discovered" in caplog.text
        assert "prefix=market-orders/history" in caplog.text

    def test_malformed_html_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        client = MagicMock()
        client.fetch_text.return_value = "<html>bad</html>"
        logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger=logger.name):
                filenames = list_snapshots("market-orders/history", date(2026, 1, 1), _SNAPSHOT_RE, client)
        finally:
            logger.removeHandler(caplog.handler)
        assert filenames == []
        assert "No snapshots discovered" in caplog.text
        assert "prefix=market-orders/history" in caplog.text


class TestBuildCacheObjects:
    def test_creates_objects_for_snapshots(self) -> None:
        html = (
            '<html><body><a href="market-orders-2026-01-01_00-00-00.v3.csv.bz2">link1</a>'
            '<a href="market-orders-2026-01-01_12-00-00.v3.csv.bz2">link2</a></body></html>'
        )
        with patch.object(everef_util, "EverefSnapshotClient") as mock_cls:
            mock_cls.return_value.__enter__.return_value.fetch_text.return_value = html
            objects = _build_cache_objects(date(2026, 1, 1), date(2026, 1, 1))

        assert len(objects) == 2
        assert objects[0].identity_key == {"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"}
        assert objects[1].identity_key == {"source_date": "2026-01-01", "snapshot_time": "2026-01-01_12-00-00"}

    def test_skips_dates_with_no_snapshots(self) -> None:
        with patch.object(everef_util, "EverefSnapshotClient") as mock_cls:
            mock_cls.return_value.__enter__.return_value.fetch_text.return_value = "<html></html>"
            objects = _build_cache_objects(date(2026, 1, 1), date(2026, 1, 1))
        assert objects == []


class TestListSnapshotsWithRealFixture:
    fixture_date = date(2025, 1, 1)

    # Hardcoded from the real everef listing for 2025-01-01.
    # Regenerate by running the extraction against the fixture HTML.
    EXPECTED_FILENAMES = [
        "market-orders-2025-01-01_00-15-05.v3.csv.bz2",
        "market-orders-2025-01-01_00-45-06.v3.csv.bz2",
        "market-orders-2025-01-01_01-15-05.v3.csv.bz2",
        "market-orders-2025-01-01_01-45-05.v3.csv.bz2",
        "market-orders-2025-01-01_02-15-06.v3.csv.bz2",
        "market-orders-2025-01-01_02-45-06.v3.csv.bz2",
        "market-orders-2025-01-01_03-15-05.v3.csv.bz2",
        "market-orders-2025-01-01_03-45-05.v3.csv.bz2",
        "market-orders-2025-01-01_04-15-05.v3.csv.bz2",
        "market-orders-2025-01-01_04-45-06.v3.csv.bz2",
        "market-orders-2025-01-01_05-15-05.v3.csv.bz2",
        "market-orders-2025-01-01_05-45-05.v3.csv.bz2",
        "market-orders-2025-01-01_06-15-05.v3.csv.bz2",
        "market-orders-2025-01-01_06-45-06.v3.csv.bz2",
        "market-orders-2025-01-01_07-15-06.v3.csv.bz2",
        "market-orders-2025-01-01_07-45-05.v3.csv.bz2",
        "market-orders-2025-01-01_08-15-05.v3.csv.bz2",
        "market-orders-2025-01-01_08-45-06.v3.csv.bz2",
        "market-orders-2025-01-01_09-15-06.v3.csv.bz2",
        "market-orders-2025-01-01_09-45-06.v3.csv.bz2",
        "market-orders-2025-01-01_10-15-06.v3.csv.bz2",
        "market-orders-2025-01-01_10-45-06.v3.csv.bz2",
        "market-orders-2025-01-01_11-45-05.v3.csv.bz2",
        "market-orders-2025-01-01_12-15-05.v3.csv.bz2",
        "market-orders-2025-01-01_12-45-06.v3.csv.bz2",
        "market-orders-2025-01-01_13-15-06.v3.csv.bz2",
        "market-orders-2025-01-01_13-45-05.v3.csv.bz2",
        "market-orders-2025-01-01_14-15-06.v3.csv.bz2",
        "market-orders-2025-01-01_14-45-05.v3.csv.bz2",
        "market-orders-2025-01-01_15-15-06.v3.csv.bz2",
        "market-orders-2025-01-01_15-45-05.v3.csv.bz2",
        "market-orders-2025-01-01_16-15-06.v3.csv.bz2",
        "market-orders-2025-01-01_16-45-05.v3.csv.bz2",
        "market-orders-2025-01-01_17-15-06.v3.csv.bz2",
        "market-orders-2025-01-01_17-45-05.v3.csv.bz2",
        "market-orders-2025-01-01_18-15-05.v3.csv.bz2",
        "market-orders-2025-01-01_18-45-06.v3.csv.bz2",
        "market-orders-2025-01-01_19-15-05.v3.csv.bz2",
        "market-orders-2025-01-01_19-45-06.v3.csv.bz2",
        "market-orders-2025-01-01_20-15-05.v3.csv.bz2",
        "market-orders-2025-01-01_20-45-06.v3.csv.bz2",
        "market-orders-2025-01-01_21-15-06.v3.csv.bz2",
        "market-orders-2025-01-01_21-45-05.v3.csv.bz2",
        "market-orders-2025-01-01_22-15-06.v3.csv.bz2",
        "market-orders-2025-01-01_22-45-06.v3.csv.bz2",
        "market-orders-2025-01-01_23-15-06.v3.csv.bz2",
        "market-orders-2025-01-01_23-45-06.v3.csv.bz2",
    ]

    def test_extracts_all_snapshots(self, real_listing_html: str) -> None:
        client = MagicMock()
        client.fetch_text.return_value = real_listing_html
        filenames = list_snapshots("market-orders/history", self.fixture_date, _SNAPSHOT_RE, client)
        assert filenames == self.EXPECTED_FILENAMES


class TestBuildCacheObjectsWithRealFixture:
    fixture_date = date(2025, 1, 1)
    EXPECTED_FILENAMES = TestListSnapshotsWithRealFixture.EXPECTED_FILENAMES

    def test_builds_cache_objects_from_real_listing(self, real_listing_html: str) -> None:
        with patch.object(everef_util, "EverefSnapshotClient") as mock_cls:
            mock_cls.return_value.__enter__.return_value.fetch_text.return_value = real_listing_html
            objects = _build_cache_objects(self.fixture_date, self.fixture_date)
        assert len(objects) == len(self.EXPECTED_FILENAMES)

        first_id = self.EXPECTED_FILENAMES[0].replace("market-orders-", "").replace(".v3.csv.bz2", "")
        assert objects[0].identity_key == {"source_date": "2025-01-01", "snapshot_time": first_id}
        assert objects[0].source_url == (
            f"https://data.everef.net/market-orders/history/2025/2025-01-01/{self.EXPECTED_FILENAMES[0]}"
        )

        last_id = self.EXPECTED_FILENAMES[-1].replace("market-orders-", "").replace(".v3.csv.bz2", "")
        assert objects[-1].identity_key == {"source_date": "2025-01-01", "snapshot_time": last_id}
        assert objects[-1].source_url == (
            f"https://data.everef.net/market-orders/history/2025/2025-01-01/{self.EXPECTED_FILENAMES[-1]}"
        )


class TestReadCsvToArrow:
    CSV_CONTENT = (
        "order_id,type_id,region_id,location_id,system_id,"
        "range,price,volume_remain,volume_total,min_volume,issued,expires,duration,is_buy_order,reported_by,http_last_modified\n"
        "1,34,10000001,60000001,30000001,0,9.99,10,100,1,2026-01-01T00:00:00Z,2026-02-01T00:00:00Z,30,True,1000001,2026-01-01T00:00:00Z\n"
    )

    @pytest.fixture
    def csv_path(self, tmp_path: pathlib.Path) -> pathlib.Path:
        path = tmp_path / "market-orders-2026-01-01_00-00-00.v3.csv.bz2"
        with bz2.open(path, "wt") as f:
            f.write(self.CSV_CONTENT)
        return path

    def test_adds_provenance(self, csv_path: pathlib.Path) -> None:
        result = make_cache_result(
            str(csv_path),
            content_length=csv_path.stat().st_size,
            last_modified="2026-01-01T00:00:00Z",
            dataset_name="market-orders",
            identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
            source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/market-orders-2026-01-01_00-00-00.v3.csv.bz2",
        )
        table = read_csv_to_arrow(result)

        assert "order_id" in table.column_names
        assert "_source_market_date" in table.column_names
        assert len(table) == 1
        assert table.column("_source_market_date")[0].as_py() == "2026-01-01"
        assert table.column("_source_local_path")[0].as_py() == str(csv_path)

    def test_zero_row_warning(self, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
        path = tmp_path / "empty.csv.bz2"
        with bz2.open(path, "wt") as f:
            f.write("order_id,type_id\n")
        result = make_cache_result(
            str(path),
            dataset_name="market-orders",
            identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
            source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/market-orders-2026-01-01_00-00-00.v3.csv.bz2",
        )
        logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger=logger.name):
                table = read_csv_to_arrow(result)
        finally:
            logger.removeHandler(caplog.handler)
        assert len(table) == 0
        assert "Zero-row CSV file" in caplog.text


def test_process_result_uses_insert_missing_keys_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    result = make_cache_result(
        "/tmp/fake.csv.bz2",
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
    )
    writer = MagicMock()
    monkeypatch.setattr(
        "ingest.sources.everef.market_orders.read_csv_to_arrow",
        lambda result: pa.table({"order_id": [1]}),
    )

    assert _process_result(result, writer) is True
    call_kwargs = writer.write.call_args.kwargs
    assert call_kwargs["mode"].value == "insert_missing_keys"
    assert call_kwargs["key_columns"] == ["order_id", "snapshot_time"]
