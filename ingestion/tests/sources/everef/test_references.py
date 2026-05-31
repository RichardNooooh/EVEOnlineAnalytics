from __future__ import annotations

import json
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

from ingest.sources.everef.references import (
    _build_cache_objects,
    _parse_json_to_table,
    _process_member,
)
from tests.sources.everef.conftest import make_cache_result


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
        writer.write.return_value = MagicMock(replaced_rows=0)
        ok, metrics = _process_member(str(member_path), "types.json", result, writer)

        assert ok is True
        assert metrics is writer.write.return_value
        writer.write.assert_called_once()
        call_kwargs = writer.write.call_args.kwargs
        assert call_kwargs["table"].value == "raw_reference_types"
        assert call_kwargs["mode"].value == "replace_table"

    def test_skips_unknown_file(self, tmp_path: Path) -> None:
        member_path = tmp_path / "unknown.json"
        member_path.write_text("[]")

        result = make_cache_result(str(tmp_path / "archive.tar.xz"))
        writer = MagicMock()
        ok, metrics = _process_member(str(member_path), "unknown.json", result, writer)

        assert ok is True
        assert metrics is None
        writer.write.assert_not_called()

    def test_handles_parse_error(self, tmp_path: Path) -> None:
        member_path = tmp_path / "types.json"
        member_path.write_text("not json")

        result = make_cache_result(str(tmp_path / "archive.tar.xz"))
        writer = MagicMock()
        ok, metrics = _process_member(str(member_path), "types.json", result, writer)

        assert ok is False
        assert metrics is None
        writer.write.assert_not_called()
