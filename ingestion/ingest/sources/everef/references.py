from __future__ import annotations

import json
from datetime import UTC, datetime

import pyarrow as pa

from ingest.archive.tarball import ExtractedTarball
from ingest.cache import Cache, CacheObject, CacheResult, GetMode, UpdateMode
from ingest.publishers.ducklake import (
    DuckLakeWriter,
    RawDuckLakeTable,
    build_ducklake_attach_config_from_url,
)
from ingest.sources.everef.logger import logger
from ingest.util import file_size

EVEREF_BASE = "https://data.everef.net"

# Map JSON filename (without .json) to (RawDuckLakeTable, key_column)
_REFERENCE_TABLES: dict[str, tuple[RawDuckLakeTable, str]] = {
    "types": (RawDuckLakeTable.REFERENCE_TYPES, "type_id"),
    "regions": (RawDuckLakeTable.REFERENCE_REGIONS, "region_id"),
    "groups": (RawDuckLakeTable.REFERENCE_GROUPS, "group_id"),
    "categories": (RawDuckLakeTable.REFERENCE_CATEGORIES, "category_id"),
}


def _build_cache_object() -> list[CacheObject]:
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
    n = len(table)
    content_length = file_size(result.path)
    now = datetime.now(UTC)

    provenance = [
        ("_source_url", pa.array([result.version.source_url] * n, type=pa.utf8())),
        ("_source_local_path", pa.array([result.path] * n, type=pa.utf8())),
        ("_source_sha256", pa.array([result.version.sha256] * n, type=pa.utf8())),
        ("_source_content_length", pa.array([content_length] * n, type=pa.int64())),
        ("_source_last_modified", pa.array([result.version.revalidation.last_modified] * n, type=pa.utf8())),
        ("_source_downloaded_at", pa.array([result.version.fetched_at] * n, type=pa.timestamp("us", tz="UTC"))),
        ("_source_archive_member", pa.array([archive_name] * n, type=pa.utf8())),
        ("_ingested_at", pa.array([now] * n, type=pa.timestamp("us", tz="UTC"))),
    ]
    for name, col in provenance:
        table = table.append_column(name, col)

    return table


def _process_member(member_path: str, archive_name: str, result: CacheResult, writer: DuckLakeWriter) -> bool:
    filename = archive_name
    if filename.endswith(".json"):
        filename = filename[:-5]

    table_info = _REFERENCE_TABLES.get(filename)
    if table_info is None:
        logger.debug("Skipping unknown reference file archive_member=%s", archive_name)
        return True

    table_key, key_column = table_info

    try:
        table = _parse_json_to_table(member_path, result, archive_name)
        if table.num_rows == 0:
            logger.warning("Zero-row table for archive_member=%s", archive_name)
            return True

        writer.write(table, table=table_key, key_columns=[key_column])
        logger.info(
            "Published reference table=%s rows=%d archive_member=%s key_column=%s",
            table_key.value,
            table.num_rows,
            archive_name,
            key_column,
        )
        return True
    except Exception as e:
        logger.exception("Failed to process archive_member=%s: %s", archive_name, e)
        return False


def run_pipeline(config) -> int:
    objects = _build_cache_object()

    attach_config = build_ducklake_attach_config_from_url(
        config.ducklake.ducklake_catalog,
        data_path=f"{config.data_root}/datasets/ducklake/raw",
        metadata_schema=config.ducklake.ducklake_metadata_schema,
    )

    logger.info(
        "Starting pipeline dataset=%s data_root=%s metadata_schema=%s",
        "reference-data",
        config.data_root,
        config.ducklake.ducklake_metadata_schema,
    )

    with Cache(
        dataset_name="reference-data",
        update_mode=UpdateMode.SNAPSHOT,
        raw_root=f"{config.data_root}/raw",
        ledger_url=config.raw_files.raw_ledger_url,
    ) as cache:
        results = cache.get_many(objects, mode=GetMode.UNPUBLISHED)

        if not results:
            logger.info("No unpublished raw objects to process dataset=reference-data")
            return 0

        (result,) = results
        successful = False

        with DuckLakeWriter(attach_config) as writer, ExtractedTarball(result.path) as archive:
            json_members = list(archive.iter_json_files())
            if not json_members:
                logger.warning(
                    "No JSON files found in archive identity_key=%s path=%s",
                    result.identity_key,
                    result.path,
                )

            member_success = 0
            member_failed = 0
            for member in json_members:
                if _process_member(str(member.path), member.archive_name, result, writer):
                    member_success += 1
                else:
                    member_failed += 1

            if member_failed == 0 and member_success > 0:
                successful = True
                cache.pubtrack.mark_published_many([result])
            elif member_success == 0:
                logger.error("No reference files were successfully processed")

        if successful:
            logger.info(
                "Successfully published reference data archive=%s files_processed=%d",
                result.path,
                member_success,
            )
        else:
            logger.warning(
                "Partial or failed publication archive=%s success=%d failed=%d",
                result.path,
                member_success,
                member_failed,
            )

    return 0 if successful else 1
