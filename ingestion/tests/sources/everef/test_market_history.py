from __future__ import annotations

import bz2
import pathlib
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from ingest.cache import CacheObject, CacheResult
from ingest.cli.config import DuckLakeCliConfig, EverefCliConfig, RawFilesCliConfig
import logging

from ingest.sources.everef.logger import logger
from ingest.sources.everef.market_history import (
    _build_cache_objects,
    run_pipeline,
)
from ingest.sources.everef.util import read_csv_to_arrow
from tests.sources.everef.conftest import FakeConnection, make_cache_result

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


@pytest.mark.integration
def test_run_pipeline_integration(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    csv_content = (
        "average,date,highest,lowest,order_count,volume,"
        "http_last_modified,region_id,type_id\n"
        "9.99,2026-01-01,9.99,9.99,1,24,"
        "2026-01-02T11:01:55Z,10000001,19\n"
    )
    file_path = tmp_path / "market-history-2026-01-01.csv.bz2"
    with bz2.open(file_path, "wt") as f:
        f.write(csv_content)

    fake_result = make_cache_result(str(file_path))
    mock_pubtrack = MagicMock()

    class FakeCache:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeCache:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        @property
        def pubtrack(self) -> MagicMock:
            return mock_pubtrack

        def get_many(
            self,
            objects: object,
            *,
            mode: object = None,
        ) -> list[CacheResult]:
            return [fake_result]

    con = FakeConnection()
    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)
    monkeypatch.setattr("ingest.sources.pipeline.Cache", FakeCache)
    monkeypatch.setattr(
        "ingest.sources.everef.market_history._build_cache_objects",
        lambda start, end: [
            CacheObject(
                source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
                identity_key={"source_date": "2026-01-01"},
            )
        ],
    )

    config = EverefCliConfig(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        data_root=str(tmp_path),
        raw_files=RawFilesCliConfig(
            raw_root=str(tmp_path / "raw"),
            raw_ledger_url="postgresql://fake:fake@localhost:5432/fake",
        ),
        ducklake=DuckLakeCliConfig(
            ducklake_catalog="postgresql://fake:fake@localhost:5432/fake",
            ducklake_metadata_schema="test_schema",
        ),
    )

    result = run_pipeline(config)

    assert result == 0
    mock_pubtrack.mark_published_many.assert_called_once()
    assert con.closed is True


def test_run_pipeline_only_marks_successful(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    bad_path = tmp_path / "bad.csv.bz2"
    with bz2.open(bad_path, "wt") as f:
        f.write("not,a,csv\n")

    bad_result = make_cache_result(str(bad_path))
    mock_pubtrack = MagicMock()

    class FakeCache:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeCache:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        @property
        def pubtrack(self) -> MagicMock:
            return mock_pubtrack

        def get_many(self, objects: object, *, mode: object = None) -> list[CacheResult]:
            return [bad_result]

    con = FakeConnection()
    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)
    monkeypatch.setattr("ingest.sources.pipeline.Cache", FakeCache)
    monkeypatch.setattr(
        "ingest.sources.everef.market_history._build_cache_objects",
        lambda start, end: [
            CacheObject(
                source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
                identity_key={"source_date": "2026-01-01"},
            )
        ],
    )
    # Break CSV parsing so process_result fails
    monkeypatch.setattr(
        "ingest.sources.everef.market_history.process_result",
        lambda result, writer, **kwargs: False,
    )

    config = EverefCliConfig(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        data_root=str(tmp_path),
        raw_files=RawFilesCliConfig(
            raw_root=str(tmp_path / "raw"),
            raw_ledger_url="postgresql://fake:fake@localhost:5432/fake",
        ),
        ducklake=DuckLakeCliConfig(
            ducklake_catalog="postgresql://fake:fake@localhost:5432/fake",
            ducklake_metadata_schema="test_schema",
        ),
    )

    result = run_pipeline(config)
    assert result == 1
    mock_pubtrack.mark_published_many.assert_not_called()


def test_run_pipeline_partial_success_warns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=logger.name)

    csv_content = (
        "average,date,highest,lowest,order_count,volume,"
        "http_last_modified,region_id,type_id\n"
        "9.99,2026-01-01,9.99,9.99,1,24,"
        "2026-01-02T11:01:55Z,10000001,19\n"
    )
    good_path = tmp_path / "good.csv.bz2"
    with bz2.open(good_path, "wt") as f:
        f.write(csv_content)

    bad_path = tmp_path / "bad.csv.bz2"
    with bz2.open(bad_path, "wt") as f:
        f.write("not,a,csv\n")

    good_result = make_cache_result(str(good_path))
    bad_result = make_cache_result(str(bad_path))

    call_count = 0
    original_process = __import__("ingest.sources.everef.market_history", fromlist=["process_result"]).process_result

    def flaky_process(result, writer, *, table_key, key_columns):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return original_process(result, writer, table_key=table_key, key_columns=key_columns)
        return False

    mock_pubtrack = MagicMock()

    class FakeCache:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeCache:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        @property
        def pubtrack(self) -> MagicMock:
            return mock_pubtrack

        def get_many(self, objects: object, *, mode: object = None) -> list[CacheResult]:
            return [good_result, bad_result]

    con = FakeConnection()
    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)
    monkeypatch.setattr("ingest.sources.pipeline.Cache", FakeCache)
    monkeypatch.setattr(
        "ingest.sources.everef.market_history._build_cache_objects",
        lambda start, end: [
            CacheObject(
                source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
                identity_key={"source_date": "2026-01-01"},
            ),
            CacheObject(
                source_url="https://data.everef.net/market-history/2026/market-history-2026-01-02.csv.bz2",
                identity_key={"source_date": "2026-01-02"},
            ),
        ],
    )
    monkeypatch.setattr("ingest.sources.everef.market_history.process_result", flaky_process)

    config = EverefCliConfig(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        data_root=str(tmp_path),
        raw_files=RawFilesCliConfig(
            raw_root=str(tmp_path / "raw"),
            raw_ledger_url="postgresql://fake:fake@localhost:5432/fake",
        ),
        ducklake=DuckLakeCliConfig(
            ducklake_catalog="postgresql://fake:fake@localhost:5432/fake",
            ducklake_metadata_schema="test_schema",
        ),
    )

    result = run_pipeline(config)
    logger.removeHandler(caplog.handler)
    assert result == 1
    args, _kwargs = mock_pubtrack.mark_published_many.call_args
    marked = args[0]
    assert len(marked) == 1
    assert marked[0] is good_result
    assert "Partial publication" in caplog.text
