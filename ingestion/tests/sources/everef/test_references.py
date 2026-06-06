from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.raw_objects import UpdateMode
from eve_ingest.sources.everef.reference_data import (
    PUBLISHER_SPEC,
    _build_cache_objects,
    _parse_json_to_table,
    _process_member,
)
from tests.sources.everef.conftest import make_cache_result


def test_publisher_spec_declares_reference_mutations() -> None:
    assert PUBLISHER_SPEC.dataset_name == "reference-data"
    assert PUBLISHER_SPEC.update_mode is UpdateMode.MUTABLE
    assert PUBLISHER_SPEC.data_tables == (
        RawDuckLakeTable.REFERENCE_TYPES,
        RawDuckLakeTable.REFERENCE_REGIONS,
        RawDuckLakeTable.REFERENCE_GROUPS,
        RawDuckLakeTable.REFERENCE_CATEGORIES,
        RawDuckLakeTable.REFERENCE_MARKET_GROUPS,
    )
    assert PUBLISHER_SPEC.provenance_tables == (RawDuckLakeProvenanceTable.REFERENCE_OBJECTS,)
    assert PUBLISHER_SPEC.writer_mode is DuckLakeWriterMode.REPLACE_TABLE
    assert PUBLISHER_SPEC.publication_scope({"source_date": "latest"}) == "raw:references:full_extract"


class TestBuildCacheObjects:
    def test_single_object(self) -> None:
        objects = _build_cache_objects()
        assert len(objects) == 1

        obj = objects[0]
        assert obj.source_url == "https://data.everef.net/reference-data/reference-data-latest.tar.xz"
        assert obj.identity_key == {"source_date": "latest"}


class TestParseJsonToTable:
    def test_parses_keyed_object(self, tmp_path: Path) -> None:
        member_path = tmp_path / "types.json"
        data = {
            "1": {
                "type_id": 1,
                "name": {"en": "foo", "de": "fuu"},
                "description": {"en": "foo desc"},
                "group_id": 10,
                "category_id": 20,
                "market_group_id": 30,
                "published": True,
                "mass": 99.0,
                "packaged_volume": 10.0,
                "portion_size": 1,
                "volume": 5.0,
                "icon_id": 40,
                "meta_group_id": 50,
            },
            "2": {
                "type_id": 2,
                "name": {"en": "bar"},
                "group_id": 11,
                "category_id": 21,
                "published": False,
                "portion_size": 1,
            },
        }
        member_path.write_text(json.dumps(data))

        table = _parse_json_to_table(str(member_path), "types.json")

        assert len(table) == 2
        assert "type_id" in table.column_names
        assert "name_en" in table.column_names
        assert "description_en" in table.column_names
        assert "group_id" in table.column_names
        assert table.column("name_en")[0].as_py() == "foo"
        assert table.column("description_en")[0].as_py() == "foo desc"
        assert table.column("market_group_id")[0].as_py() == 30
        assert table.column("published")[1].as_py() is False
        assert "mass" not in table.column_names
        assert "packaged_volume" not in table.column_names
        assert "portion_size" not in table.column_names

    def test_parses_without_provenance(self, tmp_path: Path) -> None:
        member_path = tmp_path / "regions.json"
        data = {
            "10000001": {
                "region_id": 10000001,
                "name": {"en": "The Forge"},
                "description": {"en": "Trade hub region"},
                "universe_id": "eve",
                "faction_id": 500001,
                "wormhole_class_id": 7,
            }
        }
        member_path.write_text(json.dumps(data))

        table = _parse_json_to_table(str(member_path), "regions.json")

        assert "region_id" in table.column_names
        assert "name_en" in table.column_names
        assert "_source_url" not in table.column_names
        assert "_source_archive_member" not in table.column_names
        assert "_ingested_at" not in table.column_names

    def test_empty_object_returns_empty_table(self, tmp_path: Path) -> None:
        member_path = tmp_path / "empty.json"
        member_path.write_text("{}")

        table = _parse_json_to_table(str(member_path), "empty.json")

        assert table.num_rows == 0

    def test_non_keyed_list_returns_empty_table(self, tmp_path: Path) -> None:
        member_path = tmp_path / "obj.json"
        member_path.write_text("[]")

        table = _parse_json_to_table(str(member_path), "obj.json")

        assert table.num_rows == 0

    def test_market_groups_projection(self, tmp_path: Path) -> None:
        member_path = tmp_path / "market_groups.json"
        data = {
            "1857": {
                "market_group_id": 1857,
                "name": {"en": "Minerals"},
                "description": {"en": "Mined goods"},
                "parent_group_id": 533,
                "has_types": True,
                "icon_id": 404,
                "child_market_group_ids": [1, 2],
                "type_ids": [34],
            }
        }
        member_path.write_text(json.dumps(data))

        table = _parse_json_to_table(str(member_path), "market_groups.json")

        assert table.num_rows == 1
        assert table.column("market_group_id")[0].as_py() == 1857
        assert table.column("name_en")[0].as_py() == "Minerals"
        assert table.column("parent_group_id")[0].as_py() == 533
        assert table.column("has_types")[0].as_py() is True
        assert "child_market_group_ids" not in table.column_names
        assert "type_ids" not in table.column_names

    def test_warns_on_id_mismatch(self, tmp_path: Path) -> None:
        member_path = tmp_path / "types.json"
        member_path.write_text(
            json.dumps(
                {"1": {"type_id": 2, "name": {"en": "foo"}, "group_id": 10, "category_id": 20, "published": True}}
            )
        )

        with patch("eve_ingest.sources.everef.reference_data.logger.warning") as mock_warning:
            table = _parse_json_to_table(str(member_path), "types.json")

        assert table.num_rows == 1
        mock_warning.assert_any_call(
            "Reference id mismatch archive_member=%s record_key=%s id_field=%s record_id=%r",
            "types.json",
            "1",
            "type_id",
            2,
        )


class TestProcessMember:
    TYPES_DATA = {
        "1": {"type_id": 1, "name": {"en": "foo"}, "group_id": 10, "category_id": 20, "published": True},
        "2": {"type_id": 2, "name": {"en": "bar"}, "group_id": 11, "category_id": 21, "published": True},
    }

    def test_processes_known_file(self, tmp_path: Path) -> None:
        member_path = tmp_path / "types.json"
        member_path.write_text(json.dumps(self.TYPES_DATA))

        result = make_cache_result(str(tmp_path / "archive.tar.xz"))

        writer = MagicMock()
        writer.write.return_value = MagicMock(replaced_rows=0)
        ok, metrics = _process_member(str(member_path), "types.json", result, writer)

        assert ok is True
        assert metrics is writer.write.return_value
        writer.write.assert_called_once()
        written_table = writer.write.call_args.args[0]
        call_kwargs = writer.write.call_args.kwargs
        assert call_kwargs["table"].value == "raw_reference_types"
        assert call_kwargs["mode"].value == "replace_table"
        assert "name_en" in written_table.column_names

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
