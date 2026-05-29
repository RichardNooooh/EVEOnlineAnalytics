from __future__ import annotations

import re
from datetime import date

import pyarrow as pa
import requests

from ingest.cache import Cache, CacheObject, CacheResult, GetMode, UpdateMode
from ingest.cli.config import EverefCliConfig
from ingest.publishers.ducklake import (
    DuckLakeWriter,
    RawDuckLakeTable,
    build_ducklake_attach_config_from_url,
)
from ingest.sources.everef.logger import logger
from ingest.sources.everef.util import read_csv_to_arrow
from ingest.util import iter_dates

EVEREF_BASE = "https://data.everef.net"

_SNAPSHOT_RE = re.compile(r'href="(market-orders-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.v3\.csv\.bz2)"')

_KEY_COLUMNS = ["order_id", "snapshot_time"]


def _list_snapshots(d: date) -> list[str]:
    url = f"{EVEREF_BASE}/market-orders/history/{d.year}/{d.isoformat()}/"
    logger.debug("Fetching snapshot listing source_date=%s url=%s", d.isoformat(), url)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    filenames = _SNAPSHOT_RE.findall(resp.text)
    if filenames:
        logger.info(
            "Discovered snapshots source_date=%s count=%d first=%s last=%s",
            d.isoformat(),
            len(filenames),
            filenames[0],
            filenames[-1],
        )
    else:
        logger.warning(
            "No market order snapshots discovered source_date=%s listing_url=%s",
            d.isoformat(),
            url,
        )
    return filenames


def _build_cache_objects(start_date: date, end_date: date) -> list[CacheObject]:
    objects: list[CacheObject] = []
    date_count = 0
    for d in iter_dates(start_date, end_date):
        date_count += 1
        filenames = _list_snapshots(d)
        for filename in filenames:
            snapshot_id = filename.replace("market-orders-", "").replace(".v3.csv.bz2", "")
            objects.append(
                CacheObject(
                    source_url=f"{EVEREF_BASE}/market-orders/history/{d.year}/{d.isoformat()}/{filename}",
                    identity_key={"source_date": d.isoformat(), "snapshot_time": snapshot_id},
                )
            )
    logger.info(
        "Built cache objects date_count=%d total_snapshots=%d",
        date_count,
        len(objects),
    )
    return objects


def _process_result(result: CacheResult, writer: DuckLakeWriter) -> bool:
    try:
        table = read_csv_to_arrow(result)
        snapshot_time = str(result.identity_key["snapshot_time"])
        n = len(table)
        table = table.append_column(
            "snapshot_time",
            pa.array([snapshot_time] * n, type=pa.utf8()),
        )
        writer.write(table, table=RawDuckLakeTable.MARKET_ORDERS, key_columns=_KEY_COLUMNS)
        return True
    except Exception as e:
        logger.exception("Failed to process %s: %s", result.identity_key, e)
        return False


def run_pipeline(config: EverefCliConfig) -> int:
    objects = _build_cache_objects(config.start_date, config.end_date)

    attach_config = build_ducklake_attach_config_from_url(
        config.ducklake.ducklake_catalog,
        data_path=f"{config.data_root}/datasets/ducklake/raw",
        metadata_schema=config.ducklake.ducklake_metadata_schema,
    )

    total = len(objects)
    success = 0
    failed = 0

    logger.info(
        "Starting pipeline dataset=%s start_date=%s end_date=%s data_root=%s metadata_schema=%s",
        "market-orders",
        config.start_date,
        config.end_date,
        config.data_root,
        config.ducklake.ducklake_metadata_schema,
    )

    with Cache(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        raw_root=f"{config.data_root}/raw",
        ledger_url=config.raw_files.raw_ledger_url,
    ) as cache:
        results = cache.get_many(objects, mode=GetMode.UNPUBLISHED)

        if not results:
            logger.info(
                "No unpublished raw objects to process dataset=%s discovered=%d",
                "market-orders",
                total,
            )
            return 0

        successful_results: list[CacheResult] = []
        with DuckLakeWriter(attach_config) as writer:
            for result in results:
                if _process_result(result, writer):
                    success += 1
                    successful_results.append(result)
                else:
                    failed += 1

        if successful_results:
            cache.pubtrack.mark_published_many(successful_results)

        if success and failed:
            logger.warning(
                "Partial publication dataset=%s success=%d failed=%d total=%d marked_published=%d",
                "market-orders",
                success,
                failed,
                total,
                len(successful_results),
            )

    logger.info(
        "Processed %d/%d snapshots (%d failed, %d marked_published)", success, total, failed, len(successful_results)
    )
    return 1 if failed else 0
