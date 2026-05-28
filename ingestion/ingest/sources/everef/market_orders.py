from __future__ import annotations

import logging
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
from ingest.sources.everef.util import read_csv_to_arrow
from ingest.util import iter_dates

logger = logging.getLogger(__name__)

EVEREF_BASE = "https://data.everef.net"

_SNAPSHOT_RE = re.compile(r'href="(market-orders-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.v3\.csv\.bz2)"')

_KEY_COLUMNS = ["order_id", "snapshot_time"]


def _list_snapshots(d: date) -> list[str]:
    url = f"{EVEREF_BASE}/market-orders/history/{d.year}/{d.isoformat()}/"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return _SNAPSHOT_RE.findall(resp.text)


def _build_cache_objects(start_date: date, end_date: date) -> list[CacheObject]:
    objects: list[CacheObject] = []
    for d in iter_dates(start_date, end_date):
        filenames = _list_snapshots(d)
        for filename in filenames:
            snapshot_id = filename.replace("market-orders-", "").replace(".v3.csv.bz2", "")
            objects.append(
                CacheObject(
                    source_url=f"{EVEREF_BASE}/market-orders/history/{d.year}/{d.isoformat()}/{filename}",
                    identity_key={"source_date": d.isoformat(), "snapshot_time": snapshot_id},
                )
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

    with Cache(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        raw_root=f"{config.data_root}/raw",
        ledger_url=config.raw_files.raw_ledger_url,
    ) as cache:
        results = cache.get_many(objects, mode=GetMode.UNPUBLISHED)

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

    logger.info("Processed %d/%d snapshots (%d failed)", success, total, failed)
    return 1 if failed else 0
