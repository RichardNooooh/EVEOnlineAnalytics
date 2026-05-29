from __future__ import annotations

import re
from datetime import date

import pyarrow as pa
import requests

from ingest.cache import CacheObject, CacheResult, UpdateMode
from ingest.cli.config import EverefCliConfig
from ingest.publishers.ducklake import DuckLakeWriter, RawDuckLakeTable
from ingest.sources.everef.logger import logger
from ingest.sources.everef.util import EVEREF_BASE, read_csv_to_arrow
from ingest.sources.pipeline import run_pipeline as _run_pipeline
from ingest.util import iter_dates

_SNAPSHOT_RE = re.compile(r'href="[^"]*(market-orders-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.v3\.csv\.bz2)"')
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
    return _run_pipeline(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        objects=_build_cache_objects(config.start_date, config.end_date),
        config=config,
        process_one=_process_result,
    )
