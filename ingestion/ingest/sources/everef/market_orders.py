from __future__ import annotations

import logging
import re
from datetime import date

import pyarrow as pa

from ingest.cache import CacheObject, CacheResult, UpdateMode
from ingest.cli.config import EverefCliConfig
from ingest.publishers.ducklake import DuckLakeWriter, DuckLakeWriterMode, RawDuckLakeTable
from ingest.sources.everef.util import build_listed_objects, read_csv_to_arrow
from ingest.sources.pipeline import run_pipeline as _run_pipeline

logger = logging.getLogger("ingest.sources.everef")

_SNAPSHOT_RE = re.compile(r'href="[^"]*(market-orders-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.v3\.csv\.bz2)"')
_KEY_COLUMNS = ["order_id", "snapshot_time"]


def _build_cache_objects(start_date: date, end_date: date) -> list[CacheObject]:
    return build_listed_objects(
        start_date,
        end_date,
        url_prefix="market-orders/history",
        filename_pattern=_SNAPSHOT_RE,
        identity_key_fn=lambda filename, d: {
            "source_date": d.isoformat(),
            "snapshot_time": filename.replace("market-orders-", "").replace(".v3.csv.bz2", ""),
        },
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
        writer.write(
            table,
            table=RawDuckLakeTable.MARKET_ORDERS,
            mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
            key_columns=_KEY_COLUMNS,
        )
        return True
    except Exception:
        logger.exception("Failed to process %s", result.identity_key)
        return False


def run_pipeline(config: EverefCliConfig) -> int:
    return _run_pipeline(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        objects=_build_cache_objects(config.start_date, config.end_date),
        config=config,
        process_one=_process_result,
    )
