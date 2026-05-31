from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

import pyarrow as pa

from ingest.archive.tarball import ExtractedTarball
from ingest.cache import CacheObject, CacheResult, UpdateMode
from ingest.cli.config import EverefReferencesCliConfig
from ingest.publishers.ducklake import DuckLakeWriteMetrics, DuckLakeWriter, DuckLakeWriterMode, RawDuckLakeTable
from ingest.sources.everef.util import EVEREF_BASE, add_provenance
from ingest.sources.pipeline import PipelineProcessResult, run_pipeline as _run_pipeline

logger = logging.getLogger("ingest.sources.everef")

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


def _english_text(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    english_value = value.get("en")
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


def _build_cache_objects() -> list[CacheObject]:
    return [
        CacheObject(
            source_url=f"{EVEREF_BASE}/reference-data/reference-data-latest.tar.xz",
            identity_key={"source_date": "latest"},
        )
    ]


def _parse_json_to_table(member_path: str, result: CacheResult, archive_name: str) -> pa.Table:
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

    table = pa.Table.from_pylist(rows)
    return add_provenance(
        table,
        result,
        extra_columns={
            "_source_archive_member": pa.array([archive_name] * len(table), type=pa.utf8()),
        },
    )


def _process_member(
    member_path: str,
    archive_name: str,
    result: CacheResult,
    writer: DuckLakeWriter,
) -> tuple[bool, DuckLakeWriteMetrics | None]:
    filename = archive_name
    if filename.endswith(".json"):
        filename = filename[:-5]

    table_info = _REFERENCE_TABLES.get(filename)
    if table_info is None:
        logger.warning("Skipping unknown reference file archive_member=%s", archive_name)
        return True, None

    table_key = table_info

    try:
        table = _parse_json_to_table(member_path, result, archive_name)
        if table.num_rows == 0:
            logger.warning("Zero-row table for archive_member=%s", archive_name)
            return True, None

        metrics = writer.write(table, table=table_key, mode=DuckLakeWriterMode.REPLACE_TABLE)
        logger.debug(
            "Published reference table=%s rows=%d archive_member=%s replaced_rows=%d",
            table_key.value,
            table.num_rows,
            archive_name,
            metrics.replaced_rows,
        )
        return True, metrics
    except Exception:
        logger.exception("Failed to process archive_member=%s", archive_name)
        return False, None


def _process_references_result(result: CacheResult, writer: DuckLakeWriter) -> PipelineProcessResult:
    with ExtractedTarball(result.path) as archive:
        json_members = list(archive.iter_json_files())
        if not json_members:
            logger.warning(
                "No JSON files found in archive identity_key=%s path=%s",
                result.identity_key,
                result.path,
            )
            return PipelineProcessResult(
                success=False, source_date=str(result.identity_key.get("source_date", "unknown"))
            )

        logger.info(
            "Reference archive summary source_date=%s member_count=%d first=%s last=%s",
            result.identity_key.get("source_date"),
            len(json_members),
            json_members[0].archive_name,
            json_members[-1].archive_name,
        )

        member_success = 0
        member_failed = 0
        metrics: list[DuckLakeWriteMetrics] = []
        for member in json_members:
            ok, write_metrics = _process_member(str(member.path), member.archive_name, result, writer)
            if ok:
                member_success += 1
                if write_metrics is not None:
                    metrics.append(write_metrics)
            else:
                member_failed += 1

        logger.info(
            "Reference archive result source_date=%s member_success=%d member_failed=%d",
            result.identity_key.get("source_date"),
            member_success,
            member_failed,
        )

        if member_failed > 0:
            logger.warning(
                "Partial or failed processing success=%d failed=%d",
                member_success,
                member_failed,
            )
            return PipelineProcessResult(
                success=False,
                source_date=str(result.identity_key.get("source_date", "unknown")),
                write_metrics=tuple(metrics),
            )
        if member_success == 0:
            logger.error("No reference files were successfully processed")
            return PipelineProcessResult(
                success=False, source_date=str(result.identity_key.get("source_date", "unknown"))
            )
        return PipelineProcessResult(
            success=True,
            source_date=str(result.identity_key.get("source_date", "unknown")),
            write_metrics=tuple(metrics),
        )


def run_pipeline(config: EverefReferencesCliConfig) -> int:
    return _run_pipeline(
        dataset_name="reference-data",
        update_mode=UpdateMode.MUTABLE,
        objects=_build_cache_objects(),
        config=config,
        process_one=_process_references_result,
    )
