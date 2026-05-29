from __future__ import annotations

import json
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ingest.cache import CacheResult
from ingest.cli.config import (
    DuckLakeCliConfig,
    EverefReferencesCliConfig,
    RawFilesCliConfig,
)

from ingest.sources.everef.references import (
    _build_cache_objects,
    _parse_json_to_table,
    _process_member,
    run_pipeline,
)
from tests.sources.everef.conftest import FakeConnection, make_cache_result


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


class TestBuildCacheObject:
    def test_single_object(self) -> None:
        objects = _build_cache_objects()
        assert len(objects) == 1

        obj = objects[0]
        assert obj.source_url == "https://data.everef.net/reference-data/reference-data-latest.tar.xz"
        assert obj.identity_key == {"source_date": "latest"}


class TestParseJsonToTable:
    def test_parses_array(self, tmp_path: Path) -> None:
        member_path = tmp_path / "types.json"
        data = [{"type_id": 1, "name": "foo"}, {"type_id": 2, "name": "bar"}]
        member_path.write_text(json.dumps(data))

        result = make_cache_result(
            str(tmp_path / "archive.tar.xz"), content_length=128, last_modified="2026-01-02T11:01:55Z"
        )
        table = _parse_json_to_table(str(member_path), result, "types.json")

        assert len(table) == 2
        assert "type_id" in table.column_names
        assert "name" in table.column_names
        assert "type_id" in table.column_names

    def test_adds_provenance(self, tmp_path: Path) -> None:
        member_path = tmp_path / "regions.json"
        data = [{"region_id": 10000001, "name": "The Forge"}]
        member_path.write_text(json.dumps(data))

        result = make_cache_result(
            str(tmp_path / "archive.tar.xz"),
            content_length=128,
            last_modified="2026-01-02T11:01:55Z",
            source_url="https://data.everef.net/reference-data/reference-data-latest.tar.xz",
        )
        table = _parse_json_to_table(str(member_path), result, "regions.json")

        assert "_source_url" in table.column_names
        assert "_source_archive_member" in table.column_names
        assert "_ingested_at" in table.column_names
        assert table.column("_source_archive_member")[0].as_py() == "regions.json"
        assert table.column("_source_url")[0].as_py() == (
            "https://data.everef.net/reference-data/reference-data-latest.tar.xz"
        )
        assert table.column("_source_sha256")[0].as_py() == "abc123"

    def test_empty_list_returns_empty_table(self, tmp_path: Path) -> None:
        member_path = tmp_path / "empty.json"
        member_path.write_text("[]")

        result = make_cache_result(str(tmp_path / "archive.tar.xz"))
        table = _parse_json_to_table(str(member_path), result, "empty.json")

        assert table.num_rows == 0

    def test_non_list_returns_empty_table(self, tmp_path: Path) -> None:
        member_path = tmp_path / "obj.json"
        member_path.write_text('{"key": "value"}')

        result = make_cache_result(str(tmp_path / "archive.tar.xz"))
        table = _parse_json_to_table(str(member_path), result, "obj.json")

        assert table.num_rows == 0


class TestProcessMember:
    TYPES_DATA = [{"type_id": 1, "name": "foo"}, {"type_id": 2, "name": "bar"}]

    def test_processes_known_file(self, tmp_path: Path) -> None:
        member_path = tmp_path / "types.json"
        member_path.write_text(json.dumps(self.TYPES_DATA))

        tarball_path = tmp_path / "archive.tar.xz"
        _make_tarball(tarball_path, {"types.json": json.dumps(self.TYPES_DATA)})
        result = make_cache_result(str(tarball_path))

        writer = MagicMock()
        ok = _process_member(str(member_path), "types.json", result, writer)

        assert ok is True
        writer.write.assert_called_once()
        call_kwargs = writer.write.call_args.kwargs
        assert call_kwargs["table"].value == "raw_reference_types"
        assert call_kwargs["key_columns"] == ["type_id"]

    def test_skips_unknown_file(self, tmp_path: Path) -> None:
        member_path = tmp_path / "unknown.json"
        member_path.write_text("[]")

        result = make_cache_result(str(tmp_path / "archive.tar.xz"))
        writer = MagicMock()
        ok = _process_member(str(member_path), "unknown.json", result, writer)

        assert ok is True
        writer.write.assert_not_called()

    def test_handles_parse_error(self, tmp_path: Path) -> None:
        member_path = tmp_path / "types.json"
        member_path.write_text("not json")

        result = make_cache_result(str(tmp_path / "archive.tar.xz"))
        writer = MagicMock()
        ok = _process_member(str(member_path), "types.json", result, writer)

        assert ok is False
        writer.write.assert_not_called()


@pytest.mark.integration
def test_run_pipeline_integration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    types_data = [{"type_id": 1, "name": "foo"}]
    regions_data = [{"region_id": 10000001, "name": "The Forge"}]

    archive_path = tmp_path / "reference-data-latest.tar.xz"
    _make_tarball(
        archive_path,
        {
            "types.json": json.dumps(types_data),
            "regions.json": json.dumps(regions_data),
            "extra.json": json.dumps([{"x": 1}]),  # unknown file, should be skipped
        },
    )

    fake_result = make_cache_result(
        str(archive_path), content_length=archive_path.stat().st_size, last_modified="2026-05-28T13:16:13Z"
    )
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
            return [fake_result]

    con = FakeConnection()
    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)
    monkeypatch.setattr("ingest.sources.pipeline.Cache", FakeCache)

    config = EverefReferencesCliConfig(
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


@pytest.mark.integration
def test_run_pipeline_handles_empty_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    archive_path = tmp_path / "reference-data-latest.tar.xz"
    _make_tarball(archive_path, {})

    fake_result = make_cache_result(str(archive_path))
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
            return [fake_result]

    con = FakeConnection()
    monkeypatch.setattr("ingest.publishers.ducklake.duckdb.connect", lambda: con)
    monkeypatch.setattr("ingest.sources.pipeline.Cache", FakeCache)

    config = EverefReferencesCliConfig(
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


def test_run_pipeline_already_published(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mock_pubtrack = MagicMock()

    class FakeCacheEmpty:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeCacheEmpty:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        @property
        def pubtrack(self) -> MagicMock:
            return mock_pubtrack

        def get_many(self, objects: object, *, mode: object = None) -> list[CacheResult]:
            return []

    monkeypatch.setattr("ingest.sources.pipeline.Cache", FakeCacheEmpty)

    config = EverefReferencesCliConfig(
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
    mock_pubtrack.mark_published_many.assert_not_called()
