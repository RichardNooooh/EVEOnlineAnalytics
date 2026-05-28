from __future__ import annotations

import logging
from datetime import UTC, date, datetime

import pyarrow as pa
import pyarrow.csv as pac

from ingest.cache import Cache, CacheObject, CacheResult, GetMode, UpdateMode
from ingest.cli.config import EverefCliConfig
from ingest.publishers.ducklake import (
    DuckLakeWriter,
    RawDuckLakeTable,
    build_ducklake_attach_config_from_url,
)
from ingest.util import file_size, iter_dates

logger = logging.getLogger(__name__)

EVEREF_BASE = "https://data.everef.net"

_KEY_COLUMNS = ["date", "region_id", "type_id"]


def _build_cache_objects(start_date: date, end_date: date) -> list[CacheObject]:
    return [
        CacheObject(
            source_url=(f"{EVEREF_BASE}/market-history/{d.year}/market-history-{d.isoformat()}.csv.bz2"),
            identity_key={"source_date": d.isoformat()},
        )
        for d in iter_dates(start_date, end_date)
    ]


def _read_csv_to_arrow(
    path: str,
    *,
    source_date: str,
    source_url: str,
    source_local_path: str,
    sha256: str,
    fetched_at: datetime,
    content_length: int | None,
    last_modified: str | None,
) -> pa.Table:
    table = pac.read_csv(path)
    n = len(table)
    now = datetime.now(UTC)

    provenance = [
        ("_source_market_date", pa.array([source_date] * n, type=pa.utf8())),
        ("_source_url", pa.array([source_url] * n, type=pa.utf8())),
        ("_source_local_path", pa.array([source_local_path] * n, type=pa.utf8())),
        ("_source_sha256", pa.array([sha256] * n, type=pa.utf8())),
        ("_source_content_length", pa.array([content_length] * n, type=pa.int64())),
        ("_source_last_modified", pa.array([last_modified] * n, type=pa.utf8())),
        ("_source_downloaded_at", pa.array([fetched_at.isoformat()] * n, type=pa.utf8())),
        ("_ingested_at", pa.array([now.isoformat()] * n, type=pa.utf8())),
    ]
    for name, col in provenance:
        table = table.append_column(name, col)

    return table


def _process_result(result: CacheResult, writer: DuckLakeWriter) -> bool:
    source_date = str(result.identity_key["source_date"])
    try:
        content_length = file_size(result.path)
        last_modified = result.version.revalidation.last_modified if result.version.revalidation.last_modified else None
        table = _read_csv_to_arrow(
            result.path,
            source_date=source_date,
            source_url=result.version.source_url,
            source_local_path=result.path,
            sha256=result.version.sha256,
            fetched_at=result.version.fetched_at,
            content_length=content_length,
            last_modified=last_modified,
        )
        writer.write(
            table,
            table=RawDuckLakeTable.MARKET_HISTORY,
            key_columns=_KEY_COLUMNS,
        )
        return True
    except Exception:
        logger.exception("Failed to process date %s", source_date)
        return False


def run_pipeline(config: EverefCliConfig) -> int:
    date_objects = _build_cache_objects(config.start_date, config.end_date)

    attach_config = build_ducklake_attach_config_from_url(
        config.ducklake.ducklake_catalog,
        data_path=f"{config.data_root}/datasets/ducklake/raw",
        metadata_schema=config.ducklake.ducklake_metadata_schema,
    )

    total = len(date_objects)
    success = 0
    failed = 0

    with Cache(
        dataset_name="market-history",
        update_mode=UpdateMode.MUTABLE,
        raw_root=f"{config.data_root}/raw",
        ledger_url=config.raw_files.raw_ledger_url,
    ) as cache:
        results = cache.get_many(date_objects, mode=GetMode.UNPUBLISHED)

        if not results:
            return 0

        with DuckLakeWriter(attach_config) as writer:
            for result in results:
                if _process_result(result, writer):
                    success += 1
                else:
                    failed += 1

        if success:
            cache.pubtrack.mark_published_many(results)

    logger.info("Processed %d/%d days (%d failed)", success, total, failed)
    return 1 if failed else 0
