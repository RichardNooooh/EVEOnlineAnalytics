from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime

import pyarrow.csv as pac

from eve_ingest.raw_objects import CacheObject, CacheResult, UpdateMode
from eve_ingest.cli.config import EverefCliConfig
from eve_ingest.ducklake.writer import DuckLakeWriter
from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.sources.everef.discovery import build_listed_objects
from eve_ingest.sources.everef.csv_reader import parse_csv_to_arrow, publish_file_backed_rows
from eve_ingest.workflows.raw_file_workflow import PipelineProcessResult, run_pipeline as _run_pipeline
from eve_ingest.workflows.publisher_specs import PublisherSpec, source_date_publication_scope

logger = logging.getLogger("eve_ingest.sources.everef")

_FUZZWORK_RE = re.compile(r'href="[^"]*(fuzzwork-orderset-\d+-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.csv\.gz)"')

PUBLISHER_SPEC = PublisherSpec(
    dataset_name="fuzzwork-orders",
    update_mode=UpdateMode.SNAPSHOT,
    data_tables=(RawDuckLakeTable.FUZZWORK_ORDERS,),
    provenance_tables=(RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS,),
    writer_mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
    publication_scope_builder=source_date_publication_scope("fuzzwork_orders"),
)

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
        mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        key_columns=[],
        parse_table=lambda cache_result: parse_csv_to_arrow(
            cache_result,
            read_options=pac.ReadOptions(column_names=_FUZZWORK_COLUMN_NAMES),
            parse_options=pac.ParseOptions(delimiter="\t"),
        ),
        log_context={"order_set_id": result.identity_key.get("order_set_id")},
    )


def run_pipeline(config: EverefCliConfig) -> int:
    return _run_pipeline(
        publisher_spec=PUBLISHER_SPEC,
        objects=_build_cache_objects(config.start_date, config.end_date),
        config=config,
        process_one=_process_result,
    )
