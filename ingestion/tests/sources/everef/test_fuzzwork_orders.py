from __future__ import annotations

import gzip
import logging
import pathlib
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.raw_objects import UpdateMode
from eve_ingest.sources.everef.fuzzwork_orders import (
    PUBLISHER_SPEC,
    _FUZZWORK_COLUMN_NAMES,
    _FUZZWORK_SQL_SCHEMA,
    _FUZZWORK_RE,
    _build_cache_objects,
    _process_result,
)
from eve_ingest.sources.everef.discovery import list_snapshots
from eve_ingest.sources.everef.csv_reader import parse_csv_to_arrow
from eve_ingest.sources.everef import discovery as everef_discovery

from tests.sources.everef.conftest import make_cache_result

logger = logging.getLogger("eve_ingest.sources.everef")

import pyarrow.csv as pac  # noqa: E402

_TSV_DATA = "1\t34\t2026-01-01T00:00:00Z\tTrue\t10\t100\t1\t9.99\t60000001\t0\t30\t10000002\t161676\n"


def test_publisher_spec_declares_fuzzwork_order_mutations() -> None:
    assert PUBLISHER_SPEC.dataset_name == "fuzzwork-orders"
    assert PUBLISHER_SPEC.update_mode is UpdateMode.SNAPSHOT
    assert PUBLISHER_SPEC.data_tables == (RawDuckLakeTable.FUZZWORK_ORDERS,)
    assert PUBLISHER_SPEC.provenance_tables == (RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS,)
    assert PUBLISHER_SPEC.writer_mode is DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS
    assert PUBLISHER_SPEC.publication_scope({"source_date": "2026-01-01"}) == (
        "raw:fuzzwork_orders:source_date=2026-01-01"
    )


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
            with caplog.at_level(logging.WARNING, logger=logger.name):
                filenames = list_snapshots("fuzzwork/ordersets", date(2026, 1, 1), _FUZZWORK_RE, client)
        finally:
            logger.removeHandler(caplog.handler)
        assert filenames == []
        assert "No snapshots discovered source_date=2026-01-01" in caplog.text
        assert "prefix=fuzzwork/ordersets" in caplog.text


class TestBuildCacheObjects:
    def test_creates_objects_for_snapshots(self) -> None:
        html = (
            '<html><body><a href="fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz">link1</a>'
            '<a href="fuzzwork-orderset-42-2026-01-01_00-00-00.csv.gz">link2</a></body></html>'
        )
        with patch.object(everef_discovery, "EverefSnapshotClient") as mock_cls:
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
        with patch.object(everef_discovery, "EverefSnapshotClient") as mock_cls:
            mock_cls.return_value.__enter__.return_value.fetch_text.return_value = "<html></html>"
            objects = _build_cache_objects(date(2026, 1, 1), date(2026, 1, 1))
        assert objects == []


class TestParseCsvToArrow:
    @pytest.fixture
    def csv_path(self, tmp_path: pathlib.Path) -> pathlib.Path:
        path = tmp_path / "fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz"
        with gzip.open(path, "wt") as f:
            f.write(_TSV_DATA)
        return path

    def test_parses_without_provenance(self, csv_path: pathlib.Path) -> None:
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
        table = parse_csv_to_arrow(
            result,
            read_options=pac.ReadOptions(column_names=_FUZZWORK_COLUMN_NAMES),
            parse_options=pac.ParseOptions(delimiter="\t"),
        )

        assert "order_id" in table.column_names
        assert "order_set_id" in table.column_names
        assert "_source_market_date" not in table.column_names
        assert len(table) == 1
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
                table = parse_csv_to_arrow(result)
        finally:
            logger.removeHandler(caplog.handler)
        assert len(table) == 0
        assert "Zero-row CSV file" in caplog.text


def test_process_result_uses_append_snapshot_rows_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    result = make_cache_result(
        "/tmp/fake.csv.gz",
        dataset_name="fuzzwork-orders",
        identity_key={
            "source_date": "2026-01-01",
            "order_set_id": "161676",
            "snapshot_time": "2026-01-01_12-06-49",
        },
        source_url="https://data.everef.net/fuzzwork/ordersets/2026/2026-01-01/fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz",
    )
    writer = MagicMock()
    writer.source_object_ingested_sha256.return_value = None
    writer.source_object_version_is_ingested.return_value = False
    writer.quote_sql_string.side_effect = lambda value: repr(value)
    writer.publish_source_object_sql_rows.return_value = MagicMock(attempted_rows=0, inserted_rows=0, matched_rows=0)

    outcome = _process_result(result, writer)
    assert outcome.success is True
    assert outcome.source_date == "2026-01-01"
    assert len(outcome.write_metrics) == 1
    writer.write.assert_not_called()
    call_args = writer.publish_source_object_sql_rows.call_args
    call_kwargs = call_args.kwargs
    assert call_kwargs["mode"] is DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS
    assert call_kwargs["row_count"] is None
    assert _FUZZWORK_SQL_SCHEMA.strip() in call_args.args[0].sql


def test_fuzzwork_column_names_match_expected_layout() -> None:
    assert _FUZZWORK_COLUMN_NAMES == [
        "order_id",
        "type_id",
        "issued",
        "is_buy_order",
        "volume_remain",
        "volume_total",
        "min_volume",
        "price",
        "location_id",
        "range",
        "duration",
        "region_id",
        "order_set_id",
    ]
