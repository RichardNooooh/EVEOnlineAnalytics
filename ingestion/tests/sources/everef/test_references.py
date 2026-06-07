from __future__ import annotations

import json
import tarfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyarrow as pa

from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriteMetrics,
    DuckLakeWriterMode,
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
)
from eve_ingest.raw_objects import UpdateMode
from eve_ingest.sources.everef.reference_data import (
    PUBLISHER_SPEC,
    _build_cache_objects,
    _parse_json_to_table,
    _process_member,
    _process_references_result,
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


class _ReferenceWriter:
    def __init__(self, *, fail_write: bool = False) -> None:
        self.calls: list[tuple[str, object]] = []
        self.in_transaction = False
        self.fail_write = fail_write

    @contextmanager
    def transaction(self):
        self.calls.append(("transaction_enter", None))
        self.in_transaction = True
        try:
            yield
        except Exception:
            self.calls.append(("transaction_rollback", None))
            raise
        else:
            self.calls.append(("transaction_commit", None))
        finally:
            self.in_transaction = False

    def record_source_object(self, data: dict, *, table) -> None:
        assert self.in_transaction is True
        self.calls.append(("record", data.copy()))

    def mark_source_object_parsed(self, source_object_id: str, *, table) -> None:
        assert self.in_transaction is True
        self.calls.append(("mark_parsed", source_object_id))

    def mark_source_object_ingested(self, source_object_id: str, *, row_count: int, table) -> None:
        assert self.in_transaction is True
        self.calls.append(("mark_ingested", {"source_object_id": source_object_id, "row_count": row_count}))

    def validate_write_request(self, arrow_table: pa.Table, *, table, mode, key_columns=()) -> None:
        assert self.in_transaction is False
        self.calls.append(("validate_write", {"table": table, "mode": mode, "rows": len(arrow_table)}))

    @contextmanager
    def prepare_arrow_source(self, arrow_table: pa.Table):
        assert self.in_transaction is False
        source_name = f"source_{len([call for call in self.calls if call[0] == 'prepare_source'])}"
        self.calls.append(("prepare_source", {"source_name": source_name, "rows": len(arrow_table)}))
        try:
            yield source_name
        finally:
            self.calls.append(("drop_source", source_name))

    def write_prepared_source(self, arrow_table: pa.Table, *, source_name: str, table, mode, key_columns=()):
        assert self.in_transaction is True
        self.calls.append(("write_prepared", {"source_name": source_name, "table": table, "rows": len(arrow_table)}))
        if self.fail_write:
            raise RuntimeError("boom")
        return DuckLakeWriteMetrics(
            table=table,
            mode=mode,
            attempted_rows=len(arrow_table),
            inserted_rows=len(arrow_table),
            matched_rows=0,
            replaced_rows=0,
        )


def _write_reference_archive(path: Path, members: dict[str, object]) -> None:
    source_dir = path.parent / "archive_members"
    source_dir.mkdir()
    for name, payload in members.items():
        (source_dir / name).write_text(json.dumps(payload))

    with tarfile.open(path, mode="w:xz") as archive:
        for name in members:
            archive.add(source_dir / name, arcname=name)


def test_process_references_prepares_arrow_sources_before_ducklake_transaction(tmp_path: Path) -> None:
    archive_path = tmp_path / "reference-data-latest.tar.xz"
    _write_reference_archive(
        archive_path,
        {
            "meta.json": {"version": 1},
            "market_groups.json": {
                "1857": {
                    "market_group_id": 1857,
                    "name": {"en": "Minerals"},
                    "description": {"en": "Mined goods"},
                    "parent_group_id": 533,
                    "has_types": True,
                }
            },
        },
    )
    result = make_cache_result(str(archive_path), dataset_name="reference-data", identity_key={"source_date": "latest"})
    writer = _ReferenceWriter()

    outcome = _process_references_result(result, writer)  # type: ignore[arg-type]

    assert outcome.success is True
    assert [call[0] for call in writer.calls] == [
        "validate_write",
        "prepare_source",
        "transaction_enter",
        "record",
        "mark_parsed",
        "write_prepared",
        "mark_ingested",
        "transaction_commit",
        "drop_source",
    ]
    assert outcome.write_metrics[0].table is RawDuckLakeTable.REFERENCE_MARKET_GROUPS
    assert writer.calls[3][1]["source_object_id"] == writer.calls[4][1]
    assert writer.calls[3][1]["source_object_id"] == writer.calls[6][1]["source_object_id"]
