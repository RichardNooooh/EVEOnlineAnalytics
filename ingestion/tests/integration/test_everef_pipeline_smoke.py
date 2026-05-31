from __future__ import annotations

import bz2
import gzip
import json
import tarfile
from datetime import date
from pathlib import Path

import pytest

from ingest.cache import CacheObject
from ingest.cli.config import EverefCliConfig, EverefReferencesCliConfig
from ingest.sources.everef import fuzzwork_orders, market_history, market_orders, references
from tests.sources.everef.conftest import install_pipeline_fakes, make_cache_result, make_everef_pipeline_config


def _write_history_file(path: Path) -> None:
    path.write_bytes(
        bz2.compress(
            (
                "average,date,highest,lowest,order_count,volume,http_last_modified,region_id,type_id\n"
                "9.99,2026-01-01,9.99,9.99,1,24,2026-01-02T11:01:55Z,10000001,19\n"
            ).encode()
        )
    )


def _write_orders_file(path: Path) -> None:
    path.write_bytes(
        bz2.compress(
            (
                "order_id,type_id,region_id,location_id,system_id,range,price,volume_remain,volume_total,min_volume,issued,expires,duration,is_buy_order,reported_by,http_last_modified\n"
                "1,34,10000001,60000001,30000001,0,9.99,10,100,1,2026-01-01T00:00:00Z,2026-02-01T00:00:00Z,30,True,1000001,2026-01-01T00:00:00Z\n"
            ).encode()
        )
    )


def _write_fuzzwork_file(path: Path) -> None:
    path.write_bytes(
        gzip.compress(b"1\t34\t2026-01-01T00:00:00Z\tTrue\t10\t100\t1\t9.99\t60000001\t0\t30\t10000002\t161676\n")
    )


def _write_reference_archive(path: Path) -> None:
    staging = path.parent / "staging"
    staging.mkdir(exist_ok=True)
    (staging / "types.json").write_text(
        json.dumps({"1": {"type_id": 1, "name": {"en": "foo"}, "group_id": 10, "category_id": 20, "published": True}})
    )
    (staging / "market_groups.json").write_text(
        json.dumps(
            {"1857": {"market_group_id": 1857, "name": {"en": "Minerals"}, "parent_group_id": 533, "has_types": True}}
        )
    )
    with tarfile.open(path, "w:xz") as archive:
        archive.add(staging / "types.json", arcname="types.json")
        archive.add(staging / "market_groups.json", arcname="market_groups.json")


@pytest.mark.integration
def test_market_history_pipeline_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    file_path = tmp_path / "market-history-2026-01-01.csv.bz2"
    _write_history_file(file_path)

    fake_result = make_cache_result(
        str(file_path),
        content_length=file_path.stat().st_size,
        last_modified="2026-01-02T11:01:55Z",
        source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
    )
    con, mock_pubtrack = install_pipeline_fakes(monkeypatch, [fake_result])
    monkeypatch.setattr(
        market_history,
        "_build_cache_objects",
        lambda start, end: [
            CacheObject(
                source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
                identity_key={"source_date": "2026-01-01"},
            )
        ],
    )

    config = make_everef_pipeline_config(
        EverefCliConfig,
        tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
    )

    assert market_history.run_pipeline(config) == 0
    mock_pubtrack.mark_published_many.assert_called_once()
    assert con.closed is True


@pytest.mark.integration
def test_market_orders_pipeline_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    file_path = tmp_path / "market-orders-2026-01-01_00-00-00.v3.csv.bz2"
    _write_orders_file(file_path)

    fake_result = make_cache_result(
        str(file_path),
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/market-orders-2026-01-01_00-00-00.v3.csv.bz2",
    )
    con, mock_pubtrack = install_pipeline_fakes(monkeypatch, [fake_result])
    monkeypatch.setattr(
        market_orders,
        "_build_cache_objects",
        lambda start, end: [
            CacheObject(
                source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/market-orders-2026-01-01_00-00-00.v3.csv.bz2",
                identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
            )
        ],
    )

    config = make_everef_pipeline_config(
        EverefCliConfig,
        tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
    )

    assert market_orders.run_pipeline(config) == 0
    mock_pubtrack.mark_published_many.assert_called_once()
    assert con.closed is True


@pytest.mark.integration
def test_fuzzwork_orders_pipeline_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    file_path = tmp_path / "fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz"
    _write_fuzzwork_file(file_path)

    fake_result = make_cache_result(
        str(file_path),
        dataset_name="fuzzwork-orders",
        identity_key={"source_date": "2026-01-01", "order_set_id": "161676", "snapshot_time": "2026-01-01_12-06-49"},
        source_url="https://data.everef.net/fuzzwork/ordersets/2026/2026-01-01/fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz",
    )
    con, mock_pubtrack = install_pipeline_fakes(monkeypatch, [fake_result])
    monkeypatch.setattr(
        fuzzwork_orders,
        "_build_cache_objects",
        lambda start, end: [
            CacheObject(
                source_url="https://data.everef.net/fuzzwork/ordersets/2026/2026-01-01/fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz",
                identity_key={
                    "source_date": "2026-01-01",
                    "order_set_id": "161676",
                    "snapshot_time": "2026-01-01_12-06-49",
                },
            )
        ],
    )

    config = make_everef_pipeline_config(
        EverefCliConfig,
        tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
    )

    assert fuzzwork_orders.run_pipeline(config) == 0
    mock_pubtrack.mark_published_many.assert_called_once()
    assert con.closed is True


@pytest.mark.integration
def test_references_pipeline_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    archive_path = tmp_path / "reference-data-latest.tar.xz"
    _write_reference_archive(archive_path)

    fake_result = make_cache_result(
        str(archive_path),
        content_length=archive_path.stat().st_size,
        last_modified="2026-05-28T13:16:13Z",
        dataset_name="reference-data",
        source_url="https://data.everef.net/reference-data/reference-data-latest.tar.xz",
    )
    con, mock_pubtrack = install_pipeline_fakes(monkeypatch, [fake_result])
    monkeypatch.setattr(
        references,
        "_build_cache_objects",
        lambda: [
            CacheObject(
                source_url="https://data.everef.net/reference-data/reference-data-latest.tar.xz",
                identity_key={"source_date": "latest"},
            )
        ],
    )

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)

    assert references.run_pipeline(config) == 0
    mock_pubtrack.mark_published_many.assert_called_once()
    assert con.closed is True
