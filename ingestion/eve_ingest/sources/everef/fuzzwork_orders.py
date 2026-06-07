from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime

from eve_ingest.raw_objects import CacheObject, CacheResult, UpdateMode
from eve_ingest.cli.config import EverefCliConfig
from eve_ingest.ducklake.raw_tables import compute_source_object_id
from eve_ingest.ducklake.writer import DuckLakeSqlSnapshotSource, DuckLakeWriter
from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.sources.everef.discovery import build_listed_objects
from eve_ingest.sources.everef.csv_reader import publish_file_backed_snapshot_rows
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

_FUZZWORK_SQL_SCHEMA = """
{
    'order_id': 'BIGINT',
    'type_id': 'BIGINT',
    'issued': 'TIMESTAMP',
    'is_buy_order': 'BOOLEAN',
    'volume_remain': 'BIGINT',
    'volume_total': 'BIGINT',
    'min_volume': 'BIGINT',
    'price': 'DOUBLE',
    'location_id': 'BIGINT',
    'range': 'VARCHAR',
    'duration': 'BIGINT',
    'region_id': 'BIGINT',
    'order_set_id': 'BIGINT'
}
"""


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
    source_object_id = compute_source_object_id("fuzzwork", "fuzzwork_orders", result.version.source_url)
    path_sql = writer.quote_sql_string(result.path)
    source_object_id_sql = writer.quote_sql_string(source_object_id)
    source_market_date_sql = writer.quote_sql_string(source_market_date.isoformat())
    snapshot_ts_sql = writer.quote_sql_string(snapshot_ts.isoformat())
    sql_source = DuckLakeSqlSnapshotSource(
        sql=f"""
        SELECT
            order_id,
            type_id,
            issued,
            is_buy_order,
            volume_remain,
            volume_total,
            min_volume,
            price,
            location_id,
            "range" AS range,
            duration,
            region_id,
            order_set_id,
            CAST({source_object_id_sql} AS VARCHAR) AS source_object_id,
            CAST({source_market_date_sql} AS DATE) AS source_market_date,
            CAST({snapshot_ts_sql} AS TIMESTAMP WITH TIME ZONE) AS snapshot_ts
        FROM read_csv(
            {path_sql},
            auto_detect = false,
            header = false,
            compression = 'gzip',
            delim = '\t',
            columns = {_FUZZWORK_SQL_SCHEMA},
            timestampformat = '%Y-%m-%dT%H:%M:%SZ'
        )
        """
    )
    return publish_file_backed_snapshot_rows(
        result,
        writer,
        source_system="fuzzwork",
        endpoint="fuzzwork_orders",
        source_market_date=source_market_date,
        snapshot_ts=snapshot_ts,
        table_key=RawDuckLakeTable.FUZZWORK_ORDERS,
        sql_source=sql_source,
        log_context={"order_set_id": result.identity_key.get("order_set_id")},
    )


def run_pipeline(config: EverefCliConfig) -> int:
    return _run_pipeline(
        publisher_spec=PUBLISHER_SPEC,
        objects=_build_cache_objects(config.start_date, config.end_date),
        config=config,
        process_one=_process_result,
    )
