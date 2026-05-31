from __future__ import annotations

import json
import logging

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

    if not isinstance(data, list) or not data:
        logger.warning("Empty or non-list JSON in archive member=%s", archive_name)
        return pa.Table.from_pydict({})

    table = pa.Table.from_pylist(data)
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
