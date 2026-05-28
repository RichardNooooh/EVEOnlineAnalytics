from __future__ import annotations

import bz2
import pathlib
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pyarrow as pa
import pytest

from ingest.cache import CacheObject, CacheResult, CacheResultStatus
from ingest.cache.client_types import RevalidationMetadata
from ingest.cache.ledger.types import RawObjectEntry, RawObjectRef, RawObjectVersion
from ingest.cache.primitives import UpdateMode
from ingest.cli.config import DuckLakeCliConfig, EverefCliConfig, RawFilesCliConfig
from ingest.sources.everef.market_history import (
    _build_cache_objects,
    run_pipeline,
)
from ingest.sources.everef.util import read_csv_to_arrow

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


def _make_result(
    file_path: str,
    *,
    content_length: int | None = None,
    last_modified: str | None = None,
) -> CacheResult:
    ref = RawObjectRef(
        source_name="everef",
        dataset_name="market-history",
        identity_hash="abc",
        identity_key={"source_date": "2026-01-01"},
        update_mode=UpdateMode.SNAPSHOT,
    )
    raw_object = RawObjectEntry(
        id="obj-1",
        ref=ref,
        created_at=datetime(2026, 1, 2, 11, 1, 55, tzinfo=UTC),
    )
    version = RawObjectVersion(
        id="ver-1",
        raw_object_id="obj-1",
        source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
        fetched_at=datetime(2026, 1, 2, 11, 1, 55, tzinfo=UTC),
        revalidation=RevalidationMetadata(content_length=content_length, last_modified=last_modified),
        sha256="abc123",
        local_path=file_path,
        storage_encoding="bz2",
        version_number=1,
    )
    return CacheResult(
        status=CacheResultStatus.STORED,
        raw_object=raw_object,
        version=version,
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
        result = _make_result(
            str(csv_path),
            content_length=csv_path.stat().st_size,
            last_modified="2026-01-02T11:01:55Z",
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
        result = _make_result(str(csv_path), last_modified=None)
        table = read_csv_to_arrow(result)

        assert "_source_last_modified" in table.column_names
        assert "_source_content_length" in table.column_names
        assert table.column("_source_last_modified")[0].as_py() is None
        assert table.column("_source_content_length")[0].as_py() == csv_path.stat().st_size


class FakeRelation:
    def __init__(self) -> None:
        self.view_names: list[str] = []

    def create_view(self, view_name: str) -> None:
        self.view_names.append(view_name)


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str] | None]] = []
        self.relation = FakeRelation()
        self.arrow_tables: list[pa.Table] = []
        self.closed = False

    def execute(self, query: str, params: list[str] | None = None) -> None:
        self.calls.append((query, params))

    def from_arrow(self, arrow_table: pa.Table) -> FakeRelation:
        self.arrow_tables.append(arrow_table)
        return self.relation

    def close(self) -> None:
        self.closed = True


def _fake_cache_result(file_path: str) -> CacheResult:
    ref = RawObjectRef(
        source_name="everef",
        dataset_name="market-history",
        identity_hash="abc",
        identity_key={"source_date": "2026-01-01"},
        update_mode=UpdateMode.SNAPSHOT,
    )
    raw_object = RawObjectEntry(
        id="obj-1",
        ref=ref,
        created_at=datetime(2026, 1, 2, 11, 1, 55, tzinfo=UTC),
    )
    version = RawObjectVersion(
        id="ver-1",
        raw_object_id="obj-1",
        source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
        fetched_at=datetime(2026, 1, 2, 11, 1, 55, tzinfo=UTC),
        revalidation=RevalidationMetadata(),
        sha256="abc123",
        local_path=file_path,
        storage_encoding="bz2",
        version_number=1,
    )
    return CacheResult(
        status=CacheResultStatus.STORED,
        raw_object=raw_object,
        version=version,
    )


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

    fake_result = _fake_cache_result(str(file_path))
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
    monkeypatch.setattr("ingest.sources.everef.market_history.Cache", FakeCache)
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
