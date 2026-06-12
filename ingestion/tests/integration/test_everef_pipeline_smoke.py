from __future__ import annotations

import bz2
import gzip
import json
import tarfile
from contextlib import contextmanager
from datetime import date
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from eve_ingest.cli.config import EverefCliConfig, EverefReferencesCliConfig
from eve_ingest.ducklake.locks import DuckLakeLockToken
from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable, compute_source_ref_id
from eve_ingest.raw_objects import AcquiredRawObject, RawObjectRequest
from eve_ingest.raw_objects.ledger.models import CurrentRawObjectState
from eve_ingest.raw_objects.models import AcquisitionMode
from eve_ingest.sources.everef import fuzzwork_orders, market_history, market_orders, reference_data
from tests.sources.everef.conftest import make_cache_result, make_everef_pipeline_config

from .conftest import ATTACH

if TYPE_CHECKING:
    from pathlib import Path

    import duckdb


def _install_pipeline_infrastructure(
    monkeypatch: pytest.MonkeyPatch,
    results: list[AcquiredRawObject],
    *,
    assert_mode: AcquisitionMode = AcquisitionMode.CHANGED,
) -> MagicMock:
    mock_pubtrack = MagicMock()
    mock_pubtrack.filter_published.return_value = set()
    mock_pubtrack.filter_unpublished.side_effect = lambda results: results

    @contextmanager
    def fake_hold_ducklake_lock_domains(
        *,
        catalog_url: str = "",
        lock_domains: tuple[str, ...] = (),
        timeout_seconds: float = 60.0,
        context: object = None,
    ):
        yield DuckLakeLockToken.unsafe_for_tests(lock_domains)

    class FakeRawObjectStore:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeRawObjectStore:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        @property
        def ledger(self) -> MagicMock:
            return MagicMock()

        @property
        def pubtrack(self) -> MagicMock:
            return mock_pubtrack

        def get_many(self, objects: object, *, mode: object = None) -> list[AcquiredRawObject]:
            assert mode is assert_mode
            return results

        def acquire_many(self, objects: object) -> list[AcquiredRawObject]:
            return results

        def load_current_states_for_results(
            self, selected: list[AcquiredRawObject]
        ) -> dict[str, CurrentRawObjectState | None]:
            return {
                result.raw_object.ref.identity_hash: CurrentRawObjectState(
                    raw_object=result.raw_object,
                    current_version=result.version,
                )
                for result in selected
            }

        def filter_current_versions(self, results: list[AcquiredRawObject]) -> tuple[list[AcquiredRawObject], int, int]:
            return results, 0, 0

    monkeypatch.setattr("eve_ingest.raw_objects.store.RawObjectStore", FakeRawObjectStore)
    monkeypatch.setattr("eve_ingest.publication.runner.RawObjectStore", FakeRawObjectStore)
    monkeypatch.setattr(
        "eve_ingest.publication.runner.hold_ducklake_lock_domains",
        fake_hold_ducklake_lock_domains,
    )
    monkeypatch.setattr(
        "eve_ingest.publication.runner.build_ducklake_attach_config_from_url",
        lambda *args, **kwargs: ATTACH,
    )
    return mock_pubtrack


def _write_history_file(path: Path) -> None:
    path.write_bytes(
        bz2.compress(
            b"average,date,highest,lowest,order_count,volume,http_last_modified,region_id,type_id\n"
            b"9.99,2026-01-01,9.99,9.99,1,24,2026-01-02T11:01:55Z,10000001,19\n"
        )
    )


def _write_orders_file(path: Path) -> None:
    path.write_bytes(
        bz2.compress(
            b"duration,is_buy_order,issued,location_id,min_volume,order_id,price,range,system_id,type_id,volume_remain,volume_total,http_last_modified,station_id,region_id,constellation_id\n"
            b"30,True,2026-01-01T00:00:00Z,60000001,1,1,9.99,0,30000001,34,10,100,2026-01-01T00:00:00Z,60000001,10000001,20000001\n"
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


@pytest.mark.real_duckdb
def test_market_history_pipeline_smoke(
    monkeypatch: pytest.MonkeyPatch, shared_con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    file_path = tmp_path / "market-history-2026-01-01.csv.bz2"
    _write_history_file(file_path)

    fake_result = make_cache_result(
        str(file_path),
        content_length=file_path.stat().st_size,
        last_modified="2026-01-02T11:01:55Z",
        source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
    )
    mock_pubtrack = _install_pipeline_infrastructure(monkeypatch, [fake_result])
    monkeypatch.setattr(
        market_history,
        "discover_objects",
        lambda _config: [
            RawObjectRequest(
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

    expected_source_ref_id = compute_source_ref_id("everef", "market_history", fake_result.version.source_url)
    prov_rows = shared_con.execute(
        f'SELECT source_ref_id, status FROM "memory"."raw"."{RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS.value}"'
    ).fetchall()
    assert prov_rows == [(expected_source_ref_id, "ingested")]

    data_rows = shared_con.execute(
        f'SELECT COUNT(*) FROM "memory"."raw"."{RawDuckLakeTable.MARKET_HISTORY.value}"'
    ).fetchone()
    assert data_rows is not None
    assert data_rows[0] == 1


@pytest.mark.real_duckdb
def test_market_orders_pipeline_smoke(
    monkeypatch: pytest.MonkeyPatch, shared_con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    file_path = tmp_path / "market-orders-2026-01-01_00-00-00.v3.csv.bz2"
    _write_orders_file(file_path)

    fake_result = make_cache_result(
        str(file_path),
        dataset_name="market-orders",
        identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
        source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/market-orders-2026-01-01_00-00-00.v3.csv.bz2",
    )
    mock_pubtrack = _install_pipeline_infrastructure(monkeypatch, [fake_result])
    monkeypatch.setattr(
        market_orders,
        "discover_objects",
        lambda _config: [
            RawObjectRequest(
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

    expected_source_ref_id = compute_source_ref_id("everef", "market_orders", fake_result.version.source_url)
    prov_rows = shared_con.execute(
        f'SELECT source_ref_id, status FROM "memory"."raw"."{RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS.value}"'
    ).fetchall()
    assert prov_rows == [(expected_source_ref_id, "ingested")]

    data_rows = shared_con.execute(
        f'SELECT COUNT(*) FROM "memory"."raw"."{RawDuckLakeTable.MARKET_ORDERS.value}"'
    ).fetchone()
    assert data_rows is not None
    assert data_rows[0] == 1


@pytest.mark.real_duckdb
def test_fuzzwork_orders_pipeline_smoke(
    monkeypatch: pytest.MonkeyPatch, shared_con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    file_path = tmp_path / "fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz"
    _write_fuzzwork_file(file_path)

    fake_result = make_cache_result(
        str(file_path),
        dataset_name="fuzzwork-orders",
        identity_key={"source_date": "2026-01-01", "order_set_id": "161676", "snapshot_time": "2026-01-01_12-06-49"},
        source_url="https://data.everef.net/fuzzwork/ordersets/2026/2026-01-01/fuzzwork-orderset-161676-2026-01-01_12-06-49.csv.gz",
    )
    mock_pubtrack = _install_pipeline_infrastructure(monkeypatch, [fake_result])
    monkeypatch.setattr(
        fuzzwork_orders,
        "discover_objects",
        lambda _config: [
            RawObjectRequest(
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

    expected_source_ref_id = compute_source_ref_id("fuzzwork", "fuzzwork_orders", fake_result.version.source_url)
    prov_rows = shared_con.execute(
        f'SELECT source_ref_id, status FROM "memory"."raw"."{RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS.value}"'
    ).fetchall()
    assert prov_rows == [(expected_source_ref_id, "ingested")]

    data_rows = shared_con.execute(
        f'SELECT COUNT(*) FROM "memory"."raw"."{RawDuckLakeTable.FUZZWORK_ORDERS.value}"'
    ).fetchone()
    assert data_rows is not None
    assert data_rows[0] == 1


@pytest.mark.real_duckdb
def test_references_pipeline_smoke(
    monkeypatch: pytest.MonkeyPatch, shared_con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    archive_path = tmp_path / "reference-data-latest.tar.xz"
    _write_reference_archive(archive_path)

    fake_result = make_cache_result(
        str(archive_path),
        content_length=archive_path.stat().st_size,
        last_modified="2026-05-28T13:16:13Z",
        dataset_name="reference-data",
        source_url="https://data.everef.net/reference-data/reference-data-latest.tar.xz",
    )
    mock_pubtrack = _install_pipeline_infrastructure(monkeypatch, [fake_result])
    monkeypatch.setattr(
        reference_data,
        "discover_objects",
        lambda _config: [
            RawObjectRequest(
                source_url="https://data.everef.net/reference-data/reference-data-latest.tar.xz",
                identity_key={"source_date": "latest"},
            )
        ],
    )

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)

    assert reference_data.run_pipeline(config) == 0
    mock_pubtrack.mark_published_many.assert_called_once()

    expected_source_ref_id = compute_source_ref_id("everef", "reference_data", fake_result.version.source_url)
    prov_rows = shared_con.execute(
        f'SELECT source_ref_id, status FROM "memory"."raw"."{RawDuckLakeProvenanceTable.REFERENCE_OBJECTS.value}"'
    ).fetchall()
    assert prov_rows == [(expected_source_ref_id, "ingested")]

    type_rows = shared_con.execute(
        f'SELECT type_id, name_en FROM "memory"."raw"."{RawDuckLakeTable.REFERENCE_TYPES.value}" ORDER BY type_id'
    ).fetchall()
    assert type_rows == [(1, "foo")]

    mg_rows = shared_con.execute(
        f'SELECT market_group_id, name_en FROM "memory"."raw"."{RawDuckLakeTable.REFERENCE_MARKET_GROUPS.value}" ORDER BY market_group_id'
    ).fetchall()
    assert mg_rows == [(1857, "Minerals")]
