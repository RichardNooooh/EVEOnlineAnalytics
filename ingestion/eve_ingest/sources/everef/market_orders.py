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
from eve_ingest.ducklake.raw_tables import compute_source_object_id
from eve_ingest.ducklake.writer import DuckLakeSqlSnapshotSource, DuckLakeWriter
from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.sources.everef.discovery import build_listed_objects
from eve_ingest.sources.everef.csv_reader import publish_file_backed_snapshot_rows
from eve_ingest.workflows.raw_file_workflow import PipelineProcessResult, run_pipeline as _run_pipeline
from eve_ingest.workflows.publisher_specs import PublisherSpec, source_date_publication_scope

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

PUBLISHER_SPEC = PublisherSpec(
    dataset_name="market-orders",
    update_mode=UpdateMode.SNAPSHOT,
    data_tables=(RawDuckLakeTable.MARKET_ORDERS,),
    provenance_tables=(RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,),
    writer_mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
    publication_scope_builder=source_date_publication_scope("market_orders"),
)


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


def _process_result(result: CacheResult, writer: DuckLakeWriter) -> PipelineProcessResult:
    source_market_date = date.fromisoformat(str(result.identity_key["source_date"]))
    snapshot_ts = datetime.strptime(str(result.identity_key["snapshot_time"]), "%Y-%m-%d_%H-%M-%S").replace(tzinfo=UTC)
    source_object_id = compute_source_object_id("everef", "market_orders", result.version.source_url)
    source_object_id_sql = writer.quote_sql_string(source_object_id)
    source_market_date_sql = writer.quote_sql_string(source_market_date.isoformat())
    snapshot_ts_sql = writer.quote_sql_string(snapshot_ts.isoformat())
    with _decompressed_snapshot_csv(result.path) as csv_path:
        path_sql = writer.quote_sql_string(csv_path)
        sql_source = DuckLakeSqlSnapshotSource(
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
                CAST({source_object_id_sql} AS VARCHAR) AS source_object_id,
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
        return publish_file_backed_snapshot_rows(
            result,
            writer,
            source_system="everef",
            endpoint="market_orders",
            source_market_date=source_market_date,
            snapshot_ts=snapshot_ts,
            table_key=RawDuckLakeTable.MARKET_ORDERS,
            sql_source=sql_source,
        )


def run_pipeline(config: EverefCliConfig) -> int:
    return _run_pipeline(
        publisher_spec=PUBLISHER_SPEC,
        objects=_build_cache_objects(config.start_date, config.end_date),
        config=config,
        process_one=_process_result,
    )
