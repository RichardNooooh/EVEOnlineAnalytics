from __future__ import annotations

import logging
import re
from datetime import date

import pyarrow as pa
import pyarrow.csv as pac

from ingest.cache import CacheObject, CacheResult, UpdateMode
from ingest.cli.config import EverefCliConfig
from ingest.publishers.ducklake import DuckLakeWriter, RawDuckLakeTable
from ingest.sources.everef.util import build_listed_objects, read_csv_to_arrow
from ingest.sources.pipeline import run_pipeline as _run_pipeline

logger = logging.getLogger("ingest.sources.everef")

_FUZZWORK_RE = re.compile(r'href="[^"]*(fuzzwork-orderset-\d+-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.csv\.gz)"')
_KEY_COLUMNS = ["order_id", "order_set_id", "snapshot_time"]

_FUZZWORK_COLUMN_NAMES = [
    "order_id",
    "type_id",
    "issued",
    "is_buy_order",
    "volume_remain",
    "volume_total",
    "min_volume",
    "price",
    "location_id",
    "range",
    "duration",
    "region_id",
    "order_set_id",
]


def _build_cache_objects(start_date: date, end_date: date) -> list[CacheObject]:
    return build_listed_objects(
        start_date,
        end_date,
        url_prefix="fuzzwork/ordersets",
        filename_pattern=_FUZZWORK_RE,
        identity_key_fn=_parse_fuzzwork_identity,
    )


def _parse_fuzzwork_identity(filename: str, d: date) -> dict[str, str]:
    name = filename.removeprefix("fuzzwork-orderset-").removesuffix(".csv.gz")
    order_set_id, snapshot_time = name.split("-", 1)
    return {"source_date": d.isoformat(), "order_set_id": order_set_id, "snapshot_time": snapshot_time}


def _process_result(result: CacheResult, writer: DuckLakeWriter) -> bool:
    try:
        table = read_csv_to_arrow(
            result,
            read_options=pac.ReadOptions(column_names=_FUZZWORK_COLUMN_NAMES),
            parse_options=pac.ParseOptions(delimiter="\t"),
        )
        n = len(table)
        snapshot_time = str(result.identity_key["snapshot_time"])
        table = table.append_column("snapshot_time", pa.array([snapshot_time] * n, type=pa.utf8()))
        writer.write(table, table=RawDuckLakeTable.FUZZWORK_ORDERS, key_columns=_KEY_COLUMNS)
        return True
    except Exception as e:
        logger.exception("Failed to process %s: %s", result.identity_key, e)
        return False


def run_pipeline(config: EverefCliConfig) -> int:
    return _run_pipeline(
        dataset_name="fuzzwork-orders",
        update_mode=UpdateMode.SNAPSHOT,
        objects=_build_cache_objects(config.start_date, config.end_date),
        config=config,
        process_one=_process_result,
    )
