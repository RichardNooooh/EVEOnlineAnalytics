from __future__ import annotations

import logging
from datetime import date

from ingest.cache import Cache, CacheObject, GetMode, UpdateMode
from ingest.cli.config import EverefCliConfig
from ingest.publishers.ducklake import (
    DuckLakeWriter,
    RawDuckLakeTable,
    build_ducklake_attach_config_from_url,
)
from ingest.sources.everef.util import process_result
from ingest.util import iter_dates

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
                if process_result(result, writer, table_key=RawDuckLakeTable.MARKET_HISTORY, key_columns=_KEY_COLUMNS):
                    success += 1
                else:
                    failed += 1

        if success:
            cache.pubtrack.mark_published_many(results)

    logger.info("Processed %d/%d days (%d failed)", success, total, failed)
    return 1 if failed else 0
