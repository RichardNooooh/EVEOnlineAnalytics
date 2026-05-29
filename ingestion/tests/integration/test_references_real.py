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
                [
                    {"type_id": 1, "name": "foo"},
                    {"type_id": 2, "name": "bar"},
                ]
            ),
            "regions.json": json.dumps(
                [
                    {"region_id": 10000001, "name": "The Forge"},
                ]
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
        assert _process_references_result(result, writer) is True

    types = shared_con.execute(
        f'SELECT type_id, name FROM "memory"."raw"."{RawDuckLakeTable.REFERENCE_TYPES.value}" ORDER BY type_id'
    ).fetchall()
    regions = shared_con.execute(
        f'SELECT region_id, name FROM "memory"."raw"."{RawDuckLakeTable.REFERENCE_REGIONS.value}" ORDER BY region_id'
    ).fetchall()

    assert types == [(1, "foo"), (2, "bar")]
    assert regions == [(10000001, "The Forge")]
