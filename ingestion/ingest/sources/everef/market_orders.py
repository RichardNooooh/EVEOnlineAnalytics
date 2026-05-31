from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime

from ingest.cache import CacheObject, CacheResult, UpdateMode
from ingest.cli.config import EverefCliConfig
from ingest.publishers.ducklake import DuckLakeWriter, DuckLakeWriterMode, RawDuckLakeTable
from ingest.sources.everef.util import build_listed_objects, parse_csv_to_arrow, publish_file_backed_rows
from ingest.sources.pipeline import PipelineProcessResult, run_pipeline as _run_pipeline

logger = logging.getLogger("ingest.sources.everef")

_SNAPSHOT_RE = re.compile(r'href="[^"]*(market-orders-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.v3\.csv\.bz2)"')
_KEY_COLUMNS = ["source_object_id", "order_id"]


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


def _process_result(result: CacheResult, writer: DuckLakeWriter) -> PipelineProcessResult:
    source_market_date = date.fromisoformat(str(result.identity_key["source_date"]))
    snapshot_ts = datetime.strptime(str(result.identity_key["snapshot_time"]), "%Y-%m-%d_%H-%M-%S").replace(tzinfo=UTC)
    return publish_file_backed_rows(
        result,
        writer,
        source_system="everef",
        endpoint="market_orders",
        source_market_date=source_market_date,
        snapshot_ts=snapshot_ts,
        table_key=RawDuckLakeTable.MARKET_ORDERS,
        mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
        key_columns=_KEY_COLUMNS,
        parse_table=parse_csv_to_arrow,
    )


def run_pipeline(config: EverefCliConfig) -> int:
    return _run_pipeline(
        dataset_name="market-orders",
        update_mode=UpdateMode.SNAPSHOT,
        objects=_build_cache_objects(config.start_date, config.end_date),
        config=config,
        process_one=_process_result,
    )
