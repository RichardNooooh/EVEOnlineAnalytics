from __future__ import annotations

import logging
from datetime import date

from eve_ingest.raw_objects import CacheObject, CacheResult, UpdateMode
from eve_ingest.cli.config import EverefCliConfig
from eve_ingest.ducklake.writer import DuckLakeWriter
from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.sources.everef.discovery import build_deterministic_objects
from eve_ingest.sources.everef.csv_reader import parse_csv_to_arrow, publish_file_backed_rows
from eve_ingest.workflows.raw_file_workflow import PipelineProcessResult, run_pipeline as _run_pipeline
from eve_ingest.workflows.publisher_specs import PublisherSpec, source_date_publication_scope

logger = logging.getLogger("eve_ingest.sources.everef")

_KEY_COLUMNS = ["date", "region_id", "type_id"]

PUBLISHER_SPEC = PublisherSpec(
    dataset_name="market-history",
    update_mode=UpdateMode.MUTABLE,
    data_tables=(RawDuckLakeTable.MARKET_HISTORY,),
    provenance_tables=(RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS,),
    writer_mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
    publication_scope_builder=source_date_publication_scope("market_history"),
)


def _build_cache_objects(start_date: date, end_date: date) -> list[CacheObject]:
    return build_deterministic_objects(
        start_date,
        end_date,
        url_prefix="market-history",
        filename_prefix="market-history-",
    )


def _process_result(result: CacheResult, writer: DuckLakeWriter) -> PipelineProcessResult:
    source_market_date = date.fromisoformat(str(result.identity_key["source_date"]))
    return publish_file_backed_rows(
        result,
        writer,
        source_system="everef",
        endpoint="market_history",
        source_market_date=source_market_date,
        table_key=RawDuckLakeTable.MARKET_HISTORY,
        mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
        key_columns=_KEY_COLUMNS,
        parse_table=parse_csv_to_arrow,
    )


def run_pipeline(config: EverefCliConfig) -> int:
    return _run_pipeline(
        publisher_spec=PUBLISHER_SPEC,
        objects=_build_cache_objects(config.start_date, config.end_date),
        config=config,
        process_one=_process_result,
    )
