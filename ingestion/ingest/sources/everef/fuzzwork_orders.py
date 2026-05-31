from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime

import pyarrow.csv as pac

from ingest.cache import CacheObject, CacheResult, UpdateMode
from ingest.cli.config import EverefCliConfig
from ingest.publishers.ducklake import DuckLakeWriter, DuckLakeWriterMode, RawDuckLakeTable
from ingest.sources.everef.util import build_listed_objects, parse_csv_to_arrow, publish_file_backed_rows
from ingest.sources.pipeline import PipelineProcessResult, run_pipeline as _run_pipeline

logger = logging.getLogger("ingest.sources.everef")

_FUZZWORK_RE = re.compile(r'href="[^"]*(fuzzwork-orderset-\d+-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.csv\.gz)"')
_KEY_COLUMNS = ["source_object_id", "order_id"]

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


def _process_result(result: CacheResult, writer: DuckLakeWriter) -> PipelineProcessResult:
    source_market_date = date.fromisoformat(str(result.identity_key["source_date"]))
    snapshot_ts = datetime.strptime(str(result.identity_key["snapshot_time"]), "%Y-%m-%d_%H-%M-%S").replace(tzinfo=UTC)
    return publish_file_backed_rows(
        result,
        writer,
        source_system="fuzzwork",
        endpoint="fuzzwork_orders",
        source_market_date=source_market_date,
        snapshot_ts=snapshot_ts,
        table_key=RawDuckLakeTable.FUZZWORK_ORDERS,
        mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
        key_columns=_KEY_COLUMNS,
        parse_table=lambda cache_result: parse_csv_to_arrow(
            cache_result,
            read_options=pac.ReadOptions(column_names=_FUZZWORK_COLUMN_NAMES),
            parse_options=pac.ParseOptions(delimiter="\t"),
        ),
        log_context={"order_set_id": result.identity_key.get("order_set_id")},
    )


def run_pipeline(config: EverefCliConfig) -> int:
    return _run_pipeline(
        dataset_name="fuzzwork-orders",
        update_mode=UpdateMode.SNAPSHOT,
        objects=_build_cache_objects(config.start_date, config.end_date),
        config=config,
        process_one=_process_result,
    )
