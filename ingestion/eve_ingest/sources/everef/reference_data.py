from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any, cast

import pyarrow as pa

from eve_ingest.archives.tarball import ExtractedTarball
from eve_ingest.raw_objects import RawObjectRequest, AcquiredRawObject, UpdateMode
from eve_ingest.cli.config import EverefReferencesCliConfig
from eve_ingest.ducklake.raw_tables import (
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
)
from eve_ingest.publication.specs import (
    DatasetPublisherSpec,
    ReplaceReferenceTables,
    StaticScope,
)
from eve_ingest.publication.context import PublishContext
from eve_ingest.publication.prepared_source import PreparedReferenceTableSource
from eve_ingest.publication.results import PublishResult
from eve_ingest.publication.runner import run_dataset_pipeline
from eve_ingest.sources.everef.discovery import EVEREF_BASE

logger = logging.getLogger(__name__)


_REFERENCE_TABLES: dict[str, RawDuckLakeTable] = {
    "types": RawDuckLakeTable.REFERENCE_TYPES,
    "regions": RawDuckLakeTable.REFERENCE_REGIONS,
    "groups": RawDuckLakeTable.REFERENCE_GROUPS,
    "categories": RawDuckLakeTable.REFERENCE_CATEGORIES,
    "market_groups": RawDuckLakeTable.REFERENCE_MARKET_GROUPS,
}

_REFERENCE_ID_FIELDS: dict[str, str] = {
    "types": "type_id",
    "regions": "region_id",
    "groups": "group_id",
    "categories": "category_id",
    "market_groups": "market_group_id",
}

PUBLISHER_SPEC = DatasetPublisherSpec(
    dataset_name="reference-data",
    update_mode=UpdateMode.MUTABLE,
    data_tables=tuple(_REFERENCE_TABLES.values()),
    provenance_tables=(RawDuckLakeProvenanceTable.REFERENCE_OBJECTS,),
    write_policy=ReplaceReferenceTables(),
    publication_scope=StaticScope("raw:references:full_extract"),
)


def _english_text(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    english_value = cast(Mapping[str, Any], value).get("en")
    return english_value if isinstance(english_value, str) else None


def _project_type_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type_id": record.get("type_id"),
        "name_en": _english_text(record.get("name")),
        "description_en": _english_text(record.get("description")),
        "group_id": record.get("group_id"),
        "category_id": record.get("category_id"),
        "market_group_id": record.get("market_group_id"),
        "published": record.get("published"),
        "volume": record.get("volume"),
        "icon_id": record.get("icon_id"),
        "meta_group_id": record.get("meta_group_id"),
    }


def _project_group_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "group_id": record.get("group_id"),
        "name_en": _english_text(record.get("name")),
        "category_id": record.get("category_id"),
        "published": record.get("published"),
        "icon_id": record.get("icon_id"),
    }


def _project_category_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "category_id": record.get("category_id"),
        "name_en": _english_text(record.get("name")),
        "published": record.get("published"),
        "icon_id": record.get("icon_id"),
    }


def _project_region_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "region_id": record.get("region_id"),
        "name_en": _english_text(record.get("name")),
        "description_en": _english_text(record.get("description")),
        "universe_id": record.get("universe_id"),
        "faction_id": record.get("faction_id"),
        "wormhole_class_id": record.get("wormhole_class_id"),
    }


def _project_market_group_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "market_group_id": record.get("market_group_id"),
        "name_en": _english_text(record.get("name")),
        "description_en": _english_text(record.get("description")),
        "parent_group_id": record.get("parent_group_id"),
        "has_types": record.get("has_types"),
        "icon_id": record.get("icon_id"),
    }


_REFERENCE_PROJECTORS: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "types": _project_type_record,
    "regions": _project_region_record,
    "groups": _project_group_record,
    "categories": _project_category_record,
    "market_groups": _project_market_group_record,
}


def discover_objects(config: EverefReferencesCliConfig) -> list[RawObjectRequest]:
    return [
        RawObjectRequest(
            source_url=f"{EVEREF_BASE}/reference-data/reference-data-latest.tar.xz",
            identity_key={"source_date": "latest"},
        )
    ]


def _parse_json_to_table(member_path: str, archive_name: str) -> pa.Table:
    with open(member_path) as f:
        data = json.load(f)

    filename = archive_name.removesuffix(".json")
    projector = _REFERENCE_PROJECTORS.get(filename)
    id_field = _REFERENCE_ID_FIELDS.get(filename)
    if projector is None or id_field is None:
        logger.warning("No projection configured for archive member=%s", archive_name)
        return pa.Table.from_pydict({})

    if not isinstance(data, dict) or not data:
        logger.warning("Empty or non-keyed JSON in archive member=%s", archive_name)
        return pa.Table.from_pydict({})

    rows: list[dict[str, Any]] = []
    mismatch_count = 0
    for record_key, record_value in data.items():
        if not isinstance(record_value, Mapping):
            logger.warning(
                "Skipping non-object reference record archive_member=%s record_key=%s",
                archive_name,
                record_key,
            )
            continue

        record_id = record_value.get(id_field)
        if record_id is None or str(record_id) != str(record_key):
            mismatch_count += 1
            logger.warning(
                "Reference id mismatch archive_member=%s record_key=%s id_field=%s record_id=%r",
                archive_name,
                record_key,
                id_field,
                record_id,
            )

        rows.append(projector(record_value))

    if not rows:
        logger.warning("No projected rows in archive member=%s", archive_name)
        return pa.Table.from_pydict({})

    if mismatch_count > 0:
        logger.warning(
            "Reference invariant warnings archive_member=%s id_field=%s mismatch_count=%d",
            archive_name,
            id_field,
            mismatch_count,
        )

    return pa.Table.from_pylist(rows)


def _prepare_reference_archive(
    *,
    raw_object: AcquiredRawObject,
) -> list[PreparedReferenceTableSource]:
    # Ownership: this helper does NOT own the ExitStack or DuckDB temp views.
    # It parses the archive and returns prepared source descriptors.
    # The caller (publish_one) passes them to the publication layer
    # (PublicationService.replace_tables), which owns the ExitStack for
    # Arrow temp-view registration and the DuckDB transaction lifecycle.
    prepared_members: list[PreparedReferenceTableSource] = []
    total_rows = 0

    with ExtractedTarball(raw_object.path) as archive:
        json_members = list(archive.iter_json_files())
        if not json_members:
            logger.warning(
                "No JSON files found in archive identity_key=%s path=%s",
                raw_object.identity_key,
                raw_object.path,
            )
            raise ValueError("no JSON files in archive")

        logger.info(
            "Reference archive summary source_date=%s member_count=%d first=%s last=%s",
            raw_object.identity_key.get("source_date"),
            len(json_members),
            json_members[0].archive_name,
            json_members[-1].archive_name,
        )

        member_success = 0
        member_failed = 0
        for member in json_members:
            try:
                prepared_member = _prepare_member_source(str(member.path), member.archive_name)
                member_success += 1
                if prepared_member is not None:
                    prepared_members.append(prepared_member)
                    total_rows += prepared_member.arrow_table.num_rows
            except Exception:
                logger.exception("Failed to process archive_member=%s", member.archive_name)
                member_failed += 1
                break

        logger.info(
            "Reference archive result source_date=%s member_success=%d member_failed=%d prepared_tables=%d total_rows=%d",
            raw_object.identity_key.get("source_date"),
            member_success,
            member_failed,
            len(prepared_members),
            total_rows,
        )

        if member_failed > 0:
            logger.warning(
                "Partial or failed processing success=%d failed=%d",
                member_success,
                member_failed,
            )
            raise ValueError(f"{member_failed} members failed")
        if member_success == 0:
            logger.error("No reference files were successfully processed")
            raise ValueError("no members processed")

    return prepared_members


def publish_one(raw_object: AcquiredRawObject, ctx: PublishContext) -> PublishResult:
    prepared_members = _prepare_reference_archive(
        raw_object=raw_object,
    )
    return ctx.replace_reference_tables(
        raw_object,
        source_system="everef",
        endpoint="reference_data",
        source_market_date=raw_object.version.fetched_at.date(),
        prepared_tables=prepared_members,
        provenance_table=RawDuckLakeProvenanceTable.REFERENCE_OBJECTS,
    )


def _prepare_member_source(
    member_path: str,
    archive_name: str,
) -> PreparedReferenceTableSource | None:
    filename = archive_name
    if filename.endswith(".json"):
        filename = filename[:-5]

    table_info = _REFERENCE_TABLES.get(filename)
    if table_info is None:
        logger.warning("Skipping unknown reference file archive_member=%s", archive_name)
        return None

    table = _parse_json_to_table(member_path, archive_name)
    if table.num_rows == 0:
        logger.warning("Zero-row table for archive_member=%s", archive_name)
        return None

    return PreparedReferenceTableSource(
        raw_object=None,
        source_system="everef",
        endpoint="reference_data",
        table=table_info,
        arrow_table=table,
    )


def run_pipeline(config: EverefReferencesCliConfig) -> int:
    return run_dataset_pipeline(
        config=config, spec=PUBLISHER_SPEC, discover_objects=discover_objects, publish_one=publish_one
    )
