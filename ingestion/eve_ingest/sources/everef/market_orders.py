from __future__ import annotations

import bz2
import logging
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from eve_ingest.raw_objects import CacheObject, CacheResult, UpdateMode
from eve_ingest.cli.config import EverefCliConfig
from eve_ingest.ducklake.session import SqlSource
from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.publication.context import PublishContext
from eve_ingest.publication.prepared_source import PreparedSnapshotSqlSource
from eve_ingest.publication.results import PublishResult
from eve_ingest.publication.runner import run_dataset_pipeline
from eve_ingest.publication.specs import (
    AppendSnapshotRows,
    DatasetPublisherSpec,
    SourceDateScope,
)
from eve_ingest.sources.everef.discovery import build_listed_objects

logger = logging.getLogger("eve_ingest.sources.everef")

_SNAPSHOT_RE = re.compile(r'href="[^"]*(market-orders-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.v3\.csv\.bz2)"')

_MARKET_ORDERS_SQL_SCHEMA = """
{
    'duration': 'BIGINT',
    'is_buy_order': 'BOOLEAN',
    'issued': 'TIMESTAMP',
    'location_id': 'BIGINT',
    'min_volume': 'BIGINT',
    'order_id': 'BIGINT',
    'price': 'DOUBLE',
    'range': 'VARCHAR',
    'system_id': 'BIGINT',
    'type_id': 'BIGINT',
    'volume_remain': 'BIGINT',
    'volume_total': 'BIGINT',
    'http_last_modified': 'TIMESTAMP',
    'station_id': 'BIGINT',
    'region_id': 'BIGINT',
    'constellation_id': 'BIGINT'
}
"""

PUBLISHER_SPEC = DatasetPublisherSpec(
    dataset_name="market-orders",
    update_mode=UpdateMode.SNAPSHOT,
    data_tables=(RawDuckLakeTable.MARKET_ORDERS,),
    provenance_tables=(RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,),
    write_policy=AppendSnapshotRows(batch_scope="source_date"),
    publication_scope=SourceDateScope("market_orders"),
)


def discover_objects(config: EverefCliConfig) -> list[CacheObject]:
    return build_listed_objects(
        config.start_date,
        config.end_date,
        url_prefix="market-orders/history",
        filename_pattern=_SNAPSHOT_RE,
        identity_key_fn=lambda filename, d: {
            "source_date": d.isoformat(),
            "snapshot_time": filename.replace("market-orders-", "").replace(".v3.csv.bz2", ""),
        },
    )


@contextmanager
def _decompressed_snapshot_csv(path: str) -> Iterator[str]:
    with NamedTemporaryFile(suffix=".csv", delete=False) as handle:
        temp_path = handle.name
    try:
        with bz2.open(path, "rb") as source, open(temp_path, "wb") as destination:
            shutil.copyfileobj(source, destination)
        yield temp_path
    finally:
        Path(temp_path).unlink(missing_ok=True)


def publish_one(raw_object: CacheResult, ctx: PublishContext) -> PublishResult:
    source_market_date = date.fromisoformat(str(raw_object.identity_key["source_date"]))
    snapshot_ts = datetime.strptime(str(raw_object.identity_key["snapshot_time"]), "%Y-%m-%d_%H-%M-%S").replace(
        tzinfo=UTC
    )
    source_ref_id = ctx.source_ref_id(
        source_system="everef", endpoint="market_orders", source_url=raw_object.version.source_url
    )
    source_ref_id_sql = ctx.quote_sql_string(source_ref_id)
    source_market_date_sql = ctx.quote_sql_string(source_market_date.isoformat())
    snapshot_ts_sql = ctx.quote_sql_string(snapshot_ts.isoformat())
    with _decompressed_snapshot_csv(raw_object.path) as csv_path:
        path_sql = ctx.quote_sql_string(csv_path)
        sql_source = SqlSource(
            sql=f"""
            SELECT
                order_id,
                type_id,
                region_id,
                location_id,
                system_id,
                "range" AS range,
                price,
                volume_remain,
                volume_total,
                min_volume,
                issued,
                CAST(NULL AS TIMESTAMP) AS expires,
                duration,
                is_buy_order,
                CAST(NULL AS BIGINT) AS reported_by,
                http_last_modified,
                station_id,
                constellation_id,
                CAST({source_ref_id_sql} AS VARCHAR) AS source_ref_id,
                CAST({source_market_date_sql} AS DATE) AS source_market_date,
                CAST({snapshot_ts_sql} AS TIMESTAMP WITH TIME ZONE) AS snapshot_ts
            FROM read_csv(
                {path_sql},
                auto_detect = false,
                header = true,
                columns = {_MARKET_ORDERS_SQL_SCHEMA},
                timestampformat = '%Y-%m-%dT%H:%M:%SZ'
            )
            """
        )
        prepared = PreparedSnapshotSqlSource(
            raw_object=raw_object,
            source_system="everef",
            endpoint="market_orders",
            source_market_date=source_market_date,
            snapshot_ts=snapshot_ts,
            table=RawDuckLakeTable.MARKET_ORDERS,
            sql_source=sql_source,
        )
        return ctx.append_snapshot_sql(prepared, source_ref_id=source_ref_id)


def run_pipeline(config: EverefCliConfig) -> int:
    return run_dataset_pipeline(
        config=config,
        spec=PUBLISHER_SPEC,
        discover_objects=discover_objects,
        publish_one=publish_one,
    )
