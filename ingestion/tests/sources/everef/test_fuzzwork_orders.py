from __future__ import annotations

import gzip
import logging
import pathlib
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import pyarrow as pa

from ingest.sources.everef.fuzzwork_orders import (
    _FUZZWORK_COLUMN_NAMES,
    _FUZZWORK_RE,
    _build_cache_objects,
    _process_result,
)
from ingest.sources.everef.util import list_snapshots, read_csv_to_arrow
from ingest.sources.everef import util as everef_util

from tests.sources.everef.conftest import make_cache_result

logger = logging.getLogger("ingest.sources.everef")

import pyarrow.csv as pac  # noqa: E402

_TSV_DATA = "1\t34\t2026-01-01T00:00:00Z\tTrue\t10\t100\t1\t9.99\t60000001\t0\t30\t10000002\t161676\n"


@pytest.fixture
def snapshot_html() -> str:
    return (
        '<html><body><a href="fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz">link1</a>'
        '<a href="fuzzwork-orderset-42-2026-01-01_00-00-00.csv.gz">link2</a></body></html>'
    )


class TestListSnapshots:
    def test_extracts_filenames(self, snapshot_html: str) -> None:
        client = MagicMock()
        client.fetch_text.return_value = snapshot_html
        filenames = list_snapshots("fuzzwork/ordersets", date(2026, 1, 1), _FUZZWORK_RE, client)
        assert filenames == [
            "fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz",
            "fuzzwork-orderset-42-2026-01-01_00-00-00.csv.gz",
        ]

    def test_empty_html_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        client = MagicMock()
        client.fetch_text.return_value = "<html></html>"
        logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.INFO, logger=logger.name):
                filenames = list_snapshots("fuzzwork/ordersets", date(2026, 1, 1), _FUZZWORK_RE, client)
        finally:
            logger.removeHandler(caplog.handler)
        assert filenames == []
        assert "Snapshot listing source_date=2026-01-01 snapshot_count=0" in caplog.text
        assert "prefix=fuzzwork/ordersets" in caplog.text

    def test_malformed_html_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        client = MagicMock()
        client.fetch_text.return_value = "<html>bad</html>"
        logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.INFO, logger=logger.name):
                filenames = list_snapshots("fuzzwork/ordersets", date(2026, 1, 1), _FUZZWORK_RE, client)
        finally:
            logger.removeHandler(caplog.handler)
        assert filenames == []
        assert "Snapshot listing source_date=2026-01-01 snapshot_count=0" in caplog.text
        assert "prefix=fuzzwork/ordersets" in caplog.text


class TestBuildCacheObjects:
    def test_creates_objects_for_snapshots(self) -> None:
        html = (
            '<html><body><a href="fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz">link1</a>'
            '<a href="fuzzwork-orderset-42-2026-01-01_00-00-00.csv.gz">link2</a></body></html>'
        )
        with patch.object(everef_util, "EverefSnapshotClient") as mock_cls:
            mock_cls.return_value.__enter__.return_value.fetch_text.return_value = html
            objects = _build_cache_objects(date(2026, 1, 1), date(2026, 1, 1))

        assert len(objects) == 2
        assert objects[0].identity_key == {
            "source_date": "2026-01-01",
            "order_set_id": "161676",
            "snapshot_time": "2026-01-01_12-06-49",
        }
        assert objects[1].identity_key == {
            "source_date": "2026-01-01",
            "order_set_id": "42",
            "snapshot_time": "2026-01-01_00-00-00",
        }

    def test_skips_dates_with_no_snapshots(self) -> None:
        with patch.object(everef_util, "EverefSnapshotClient") as mock_cls:
            mock_cls.return_value.__enter__.return_value.fetch_text.return_value = "<html></html>"
            objects = _build_cache_objects(date(2026, 1, 1), date(2026, 1, 1))
        assert objects == []


class TestReadCsvToArrow:
    @pytest.fixture
    def csv_path(self, tmp_path: pathlib.Path) -> pathlib.Path:
        path = tmp_path / "fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz"
        with gzip.open(path, "wt") as f:
            f.write(_TSV_DATA)
        return path

    def test_adds_provenance(self, csv_path: pathlib.Path) -> None:
        result = make_cache_result(
            str(csv_path),
            content_length=csv_path.stat().st_size,
            last_modified="2026-01-01T12:06:49Z",
            dataset_name="fuzzwork-orders",
            identity_key={
                "source_date": "2026-01-01",
                "order_set_id": "161676",
                "snapshot_time": "2026-01-01_12-06-49",
            },
            source_url="https://data.everef.net/fuzzwork/ordersets/2026/2026-01-01/fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz",
        )
        table = read_csv_to_arrow(
            result,
            read_options=pac.ReadOptions(column_names=_FUZZWORK_COLUMN_NAMES),
            parse_options=pac.ParseOptions(delimiter="\t"),
        )

        assert "order_id" in table.column_names
        assert "order_set_id" in table.column_names
        assert "_source_market_date" in table.column_names
        assert len(table) == 1
        assert table.column("_source_market_date")[0].as_py() == "2026-01-01"
        assert table.column("order_set_id")[0].as_py() == 161676
        assert table.column("order_id")[0].as_py() == 1

    def test_zero_row_warning(self, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
        path = tmp_path / "empty.csv.gz"
        with gzip.open(path, "wt") as f:
            f.write("order_id\ttype_id\n")
        result = make_cache_result(
            str(path),
            dataset_name="fuzzwork-orders",
            identity_key={
                "source_date": "2026-01-01",
                "order_set_id": "161676",
                "snapshot_time": "2026-01-01_12-06-49",
            },
            source_url="https://data.everef.net/fuzzwork/ordersets/2026/2026-01-01/fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz",
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
        "/tmp/fake.csv.gz",
        dataset_name="fuzzwork-orders",
        identity_key={
            "source_date": "2026-01-01",
            "order_set_id": "161676",
            "snapshot_time": "2026-01-01_12-06-49",
        },
    )
    writer = MagicMock()
    monkeypatch.setattr(
        "ingest.sources.everef.fuzzwork_orders.read_csv_to_arrow",
        lambda result, read_options=None, parse_options=None: pa.table({"order_id": [1], "order_set_id": [161676]}),
    )

    writer.write.return_value = MagicMock(attempted_rows=1, inserted_rows=1, matched_rows=0)

    outcome = _process_result(result, writer)
    assert outcome.success is True
    assert outcome.source_date == "2026-01-01"
    assert len(outcome.write_metrics) == 1
    call_kwargs = writer.write.call_args.kwargs
    assert call_kwargs["mode"].value == "insert_missing_keys"
    assert call_kwargs["key_columns"] == ["order_id", "order_set_id", "snapshot_time"]
