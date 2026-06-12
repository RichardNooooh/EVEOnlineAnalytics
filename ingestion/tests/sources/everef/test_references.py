from __future__ import annotations

import json
import tarfile
from typing import TYPE_CHECKING
from unittest.mock import ANY, MagicMock, patch

from eve_ingest.ducklake.provenance import SourceObjectProvenanceRepository
from eve_ingest.ducklake.raw_publish import RawTablePublisher
from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriteMetrics,
    DuckLakeWriterMode,
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
)
from eve_ingest.ducklake.session import DuckLakeSession
from eve_ingest.publication.context import PublishContext
from eve_ingest.publication.service import PublicationService
from eve_ingest.publication.source_prep import SourcePreparationContext
from eve_ingest.publication.specs import DatasetPublisherSpec, ReplaceReferenceTables, StaticScope
from eve_ingest.raw_objects import UpdateMode
from eve_ingest.sources.everef.reference_data import (
    PUBLISHER_SPEC,
    _parse_json_to_table,
    discover_objects,
    publish_one,
)
from tests.sources.everef.conftest import make_cache_result

if TYPE_CHECKING:
    from pathlib import Path


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
    assert isinstance(PUBLISHER_SPEC, DatasetPublisherSpec)
    assert isinstance(PUBLISHER_SPEC.write_policy, ReplaceReferenceTables)
    assert PUBLISHER_SPEC.scope_for({"source_date": "latest"}) == "raw:references:full_extract"


class TestBuildRawObjectRequests:
    def test_single_object(self) -> None:
        objects = discover_objects(MagicMock())
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

    session = MagicMock(spec=DuckLakeSession)
    session.prepare_arrow_source.return_value.__enter__.return_value = "src_market_groups"
    session.transaction.return_value.__enter__.return_value = None
    session.transaction.return_value.__exit__.return_value = None

    raw_tables = MagicMock(spec=RawTablePublisher)
    raw_tables.write_prepared_source.return_value = DuckLakeWriteMetrics(
        table=RawDuckLakeTable.REFERENCE_MARKET_GROUPS,
        mode=DuckLakeWriterMode.REPLACE_TABLE,
        attempted_rows=1,
        inserted_rows=1,
        matched_rows=0,
        replaced_rows=0,
    )

    provenance = MagicMock(spec=SourceObjectProvenanceRepository)

    spec = DatasetPublisherSpec(
        dataset_name="reference-data",
        update_mode=UpdateMode.MUTABLE,
        data_tables=(
            RawDuckLakeTable.REFERENCE_TYPES,
            RawDuckLakeTable.REFERENCE_REGIONS,
            RawDuckLakeTable.REFERENCE_GROUPS,
            RawDuckLakeTable.REFERENCE_CATEGORIES,
            RawDuckLakeTable.REFERENCE_MARKET_GROUPS,
        ),
        provenance_tables=(RawDuckLakeProvenanceTable.REFERENCE_OBJECTS,),
        publication_scope=StaticScope("raw:references:full_extract"),
        write_policy=ReplaceReferenceTables(),
    )

    prep_ctx = SourcePreparationContext(session=session)
    service = PublicationService(
        raw_tables=raw_tables,
        provenance=provenance,
        session=session,
        spec=spec,
    )
    ctx = PublishContext(
        spec=spec,
        prep_ctx=prep_ctx,
        service=service,
        publication_scope="raw:references:full_extract",
    )

    outcome = publish_one(result, ctx)

    assert outcome.success is True
    assert len(outcome.write_metrics) == 1
    assert outcome.write_metrics[0].table is RawDuckLakeTable.REFERENCE_MARKET_GROUPS

    session.prepare_arrow_source.assert_called_once()
    session.transaction.assert_called_once()
    provenance.record_source_object.assert_called_once_with(ANY, table=RawDuckLakeProvenanceTable.REFERENCE_OBJECTS)
    provenance.mark_parsed.assert_called_once_with(ANY, table=RawDuckLakeProvenanceTable.REFERENCE_OBJECTS)
    provenance.mark_ingested.assert_called_once_with(ANY, table=RawDuckLakeProvenanceTable.REFERENCE_OBJECTS)
    raw_tables.write_prepared_source.assert_called_once_with(
        ANY,
        source_name="src_market_groups",
        table=RawDuckLakeTable.REFERENCE_MARKET_GROUPS,
        mode=DuckLakeWriterMode.REPLACE_TABLE,
    )
