from __future__ import annotations

from datetime import date

from ingest.cache import Cache, CacheObject, CacheResult, GetMode, UpdateMode
from ingest.cli.config import EverefCliConfig
from ingest.publishers.ducklake import (
    DuckLakeWriter,
    RawDuckLakeTable,
    build_ducklake_attach_config_from_url,
)
from ingest.sources.everef.logger import logger
from ingest.sources.everef.util import process_result
from ingest.util import iter_dates

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

    logger.info(
        "Starting pipeline dataset=%s start_date=%s end_date=%s data_root=%s metadata_schema=%s",
        "market-history",
        config.start_date,
        config.end_date,
        config.data_root,
        config.ducklake.ducklake_metadata_schema,
    )

    with Cache(
        dataset_name="market-history",
        update_mode=UpdateMode.MUTABLE,
        raw_root=f"{config.data_root}/raw",
        ledger_url=config.raw_files.raw_ledger_url,
    ) as cache:
        results = cache.get_many(date_objects, mode=GetMode.UNPUBLISHED)

        if not results:
            logger.info(
                "No unpublished raw objects to process dataset=%s discovered=%d",
                "market-history",
                total,
            )
            return 0

        successful_results: list[CacheResult] = []
        with DuckLakeWriter(attach_config) as writer:
            for result in results:
                if process_result(result, writer, table_key=RawDuckLakeTable.MARKET_HISTORY, key_columns=_KEY_COLUMNS):
                    success += 1
                    successful_results.append(result)
                else:
                    failed += 1

        if successful_results:
            cache.pubtrack.mark_published_many(successful_results)

        if success and failed:
            logger.warning(
                "Partial publication dataset=%s success=%d failed=%d total=%d marked_published=%d",
                "market-history",
                success,
                failed,
                total,
                len(successful_results),
            )

    logger.info(
        "Processed %d/%d days (%d failed, %d marked_published)", success, total, failed, len(successful_results)
    )
    return 1 if failed else 0
