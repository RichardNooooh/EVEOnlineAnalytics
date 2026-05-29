from __future__ import annotations

import logging
import re
from datetime import date

import pyarrow as pa

from ingest.cache import CacheObject, CacheResult, UpdateMode
from ingest.cli.config import EverefCliConfig
from ingest.publishers.ducklake import DuckLakeWriter, RawDuckLakeTable
from ingest.sources.everef.util import build_snapshot_cache_objects, read_csv_to_arrow
from ingest.sources.pipeline import run_pipeline as _run_pipeline

logger = logging.getLogger("ingest.sources.everef")

_SNAPSHOT_RE = re.compile(r'href="[^"]*(market-orders-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.v3\.csv\.bz2)"')
_KEY_COLUMNS = ["order_id", "snapshot_time"]


def _build_cache_objects(start_date: date, end_date: date) -> list[CacheObject]:
    def identity_key(filename: str, d: date) -> dict[str, str]:
        snapshot_id = filename.replace("market-orders-", "").replace(".v3.csv.bz2", "")
        return {"source_date": d.isoformat(), "snapshot_time": snapshot_id}

    return build_snapshot_cache_objects(
        "market-orders/history",
        start_date,
        end_date,
        _SNAPSHOT_RE,
        identity_key,
        source_label="market-orders",
    )


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
