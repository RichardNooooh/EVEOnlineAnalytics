from __future__ import annotations

import json
from pathlib import Path
import tarfile

import duckdb
import pytest

from ingest.publishers.ducklake import DuckLakeAttachConfig, DuckLakeWriter, RawDuckLakeTable
from ingest.sources.everef.references import _process_references_result
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
    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)
    monkeypatch.setattr("ingest.publishers.ducklake._attach_ducklake", lambda c, config: None)
    yield con._con
    con._con.close()


_ATTACH = DuckLakeAttachConfig(
    attach_uri=":memory:",
    data_path="",
    metadata_schema="memory",
    alias="memory",
)


def _make_tarball(path: Path, files: dict[str, str]) -> Path:
    staging = path.parent / "staging"
    staging.mkdir(exist_ok=True)
    for name, content in files.items():
        file_path = staging / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)

    with tarfile.open(path, "w:xz") as archive:
        for file_path in staging.rglob("*"):
            if file_path.is_file():
                archive.add(file_path, arcname=str(file_path.relative_to(staging)))
    return path


@pytest.mark.integration
@pytest.mark.real_duckdb
def test_process_references_result_writes_real_tables(shared_con, tmp_path: Path) -> None:
    archive_path = tmp_path / "reference-data-latest.tar.xz"
    _make_tarball(
        archive_path,
        {
            "types.json": json.dumps(
                {
                    "1": {"type_id": 1, "name": {"en": "foo"}, "group_id": 10, "category_id": 20, "published": True},
                    "2": {"type_id": 2, "name": {"en": "bar"}, "group_id": 11, "category_id": 21, "published": True},
                }
            ),
            "regions.json": json.dumps(
                {
                    "10000001": {
                        "region_id": 10000001,
                        "name": {"en": "The Forge"},
                        "description": {"en": "Trade hub region"},
                        "universe_id": "eve",
                        "faction_id": 500001,
                        "wormhole_class_id": 7,
                    }
                }
            ),
            "market_groups.json": json.dumps(
                {
                    "1857": {
                        "market_group_id": 1857,
                        "name": {"en": "Minerals"},
                        "description": {"en": "Mined goods"},
                        "parent_group_id": 533,
                        "has_types": True,
                        "icon_id": 404,
                    }
                }
            ),
        },
    )

    result = make_cache_result(
        str(archive_path),
        content_length=archive_path.stat().st_size,
        last_modified="2026-01-02T11:01:55Z",
        dataset_name="reference-data",
        source_url="https://data.everef.net/reference-data/reference-data-latest.tar.xz",
    )

    with DuckLakeWriter(_ATTACH) as writer:
        outcome = _process_references_result(result, writer)

    assert outcome.success is True
    assert outcome.source_date == "2026-01-01"
    assert len(outcome.write_metrics) == 3

    types = shared_con.execute(
        f'SELECT type_id, name_en, group_id, category_id, published FROM "memory"."raw"."{RawDuckLakeTable.REFERENCE_TYPES.value}" ORDER BY type_id'
    ).fetchall()
    regions = shared_con.execute(
        f'SELECT region_id, name_en, universe_id, faction_id, wormhole_class_id FROM "memory"."raw"."{RawDuckLakeTable.REFERENCE_REGIONS.value}" ORDER BY region_id'
    ).fetchall()
    market_groups = shared_con.execute(
        f'SELECT market_group_id, name_en, parent_group_id, has_types FROM "memory"."raw"."{RawDuckLakeTable.REFERENCE_MARKET_GROUPS.value}" ORDER BY market_group_id'
    ).fetchall()

    assert types == [(1, "foo", 10, 20, True), (2, "bar", 11, 21, True)]
    assert regions == [(10000001, "The Forge", "eve", 500001, 7)]
    assert market_groups == [(1857, "Minerals", 533, True)]
