from __future__ import annotations

import logging
from datetime import date

import pyarrow as pa

from eve_ingest.raw_objects import CacheObject, CacheResult, UpdateMode
from eve_ingest.cli.config import EverefCliConfig
from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.publication.specs import (
    DatasetPublisherSpec,
    InsertMissingKeysAuthoritativePartition,
    SourceDateScope,
)
from eve_ingest.sources.everef.discovery import build_deterministic_objects
from eve_ingest.sources.everef.csv_io import parse_csv_to_arrow
from eve_ingest.publication.context import PublishContext
from eve_ingest.publication.results import PublishResult
from eve_ingest.publication.runner import run_dataset_pipeline

logger = logging.getLogger("eve_ingest.sources.everef")

_KEY_COLUMNS = ["date", "region_id", "type_id"]

PUBLISHER_SPEC = DatasetPublisherSpec(
    dataset_name="market-history",
    update_mode=UpdateMode.MUTABLE,
    data_tables=(RawDuckLakeTable.MARKET_HISTORY,),
    provenance_tables=(RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS,),
    write_policy=InsertMissingKeysAuthoritativePartition(
        key_columns=("date", "region_id", "type_id"),
    ),
    publication_scope=SourceDateScope("market_history"),
)


def discover_objects(config: EverefCliConfig) -> list[CacheObject]:
    return build_deterministic_objects(
        config.start_date,
        config.end_date,
        url_prefix="market-history",
        filename_prefix="market-history-",
    )


def publish_one(raw_object: CacheResult, ctx: PublishContext) -> PublishResult:
    source_market_date = date.fromisoformat(str(raw_object.identity_key["source_date"]))
    table = parse_csv_to_arrow(raw_object)
    row_count = len(table)
    source_object_id = ctx.source_object_id(
        source_system="everef",
        endpoint="market_history",
        source_url=raw_object.version.source_url,
    )
    table = table.append_column(
        "source_object_id",
        pa.array([source_object_id] * row_count, type=pa.utf8()),
    )
    table = table.append_column(
        "source_market_date",
        pa.array([source_market_date] * row_count, type=pa.date32()),
    )
    return ctx.insert_missing_keys_arrow(
        raw_object,
        source_system="everef",
        endpoint="market_history",
        source_market_date=source_market_date,
        table=RawDuckLakeTable.MARKET_HISTORY,
        arrow_table=table,
        source_object_id=source_object_id,
    )


def run_pipeline(config: EverefCliConfig) -> int:
    return run_dataset_pipeline(
        config=config, spec=PUBLISHER_SPEC, discover_objects=discover_objects, publish_one=publish_one
    )
