from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.ducklake.session import SqlSource
from eve_ingest.publication.prepared_source import PreparedSnapshotSqlSource
from eve_ingest.publication.runner import run_dataset_pipeline
from eve_ingest.publication.specs import (
    AppendSnapshotRows,
    DatasetPublisherSpec,
    SourceDateScope,
)
from eve_ingest.raw_objects import AcquiredRawObject, RawObjectRequest, UpdateMode
from eve_ingest.sources.everef.discovery import build_listed_objects

if TYPE_CHECKING:
    from eve_ingest.cli.config import EverefCliConfig
    from eve_ingest.publication.context import PublishContext
    from eve_ingest.publication.results import PublishResult

logger = logging.getLogger(__name__)

_FUZZWORK_RE = re.compile(r'href="[^"]*(fuzzwork-orderset-\d+-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.csv\.gz)"')

PUBLISHER_SPEC = DatasetPublisherSpec(
    dataset_name="fuzzwork-orders",
    update_mode=UpdateMode.SNAPSHOT,
    data_tables=(RawDuckLakeTable.FUZZWORK_ORDERS,),
    provenance_tables=(RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS,),
    write_policy=AppendSnapshotRows(),
    publication_scope=SourceDateScope("fuzzwork_orders"),
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


def discover_objects(config: EverefCliConfig) -> list[RawObjectRequest]:
    return build_listed_objects(
        config.start_date,
        config.end_date,
        url_prefix="fuzzwork/ordersets",
        filename_pattern=_FUZZWORK_RE,
        identity_key_fn=_parse_fuzzwork_identity,
    )


def _parse_fuzzwork_identity(filename: str, d: date) -> dict[str, str]:
    name = filename.removeprefix("fuzzwork-orderset-").removesuffix(".csv.gz")
    order_set_id, snapshot_time = name.split("-", 1)
    return {"source_date": d.isoformat(), "order_set_id": order_set_id, "snapshot_time": snapshot_time}


def publish_one(raw_object: AcquiredRawObject, ctx: PublishContext) -> PublishResult:
    source_market_date = date.fromisoformat(str(raw_object.identity_key["source_date"]))
    snapshot_ts = datetime.strptime(str(raw_object.identity_key["snapshot_time"]), "%Y-%m-%d_%H-%M-%S").replace(
        tzinfo=UTC
    )
    source_ref_id = ctx.source_ref_id(
        source_system="fuzzwork", endpoint="fuzzwork_orders", source_url=raw_object.version.source_url
    )
    path_sql = ctx.quote_sql_string(raw_object.path)
    source_ref_id_sql = ctx.quote_sql_string(source_ref_id)
    source_market_date_sql = ctx.quote_sql_string(source_market_date.isoformat())
    snapshot_ts_sql = ctx.quote_sql_string(snapshot_ts.isoformat())
    sql_source = SqlSource(
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
            CAST({source_ref_id_sql} AS VARCHAR) AS source_ref_id,
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
    prepared = PreparedSnapshotSqlSource(
        raw_object=raw_object,
        source_system="fuzzwork",
        endpoint="fuzzwork_orders",
        source_market_date=source_market_date,
        snapshot_ts=snapshot_ts,
        table=RawDuckLakeTable.FUZZWORK_ORDERS,
        sql_source=sql_source,
        log_context={"order_set_id": raw_object.identity_key.get("order_set_id")},
    )
    return ctx.append_snapshot_sql(prepared, source_ref_id=source_ref_id)


def run_pipeline(config: EverefCliConfig) -> int:
    return run_dataset_pipeline(
        config=config, spec=PUBLISHER_SPEC, discover_objects=discover_objects, publish_one=publish_one
    )
