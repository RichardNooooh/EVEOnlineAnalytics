from __future__ import annotations

from datetime import date

from ingest.cache import CacheObject, UpdateMode
from ingest.cli.config import EverefCliConfig
from ingest.publishers.ducklake import DuckLakeWriterMode, RawDuckLakeTable
from ingest.sources.everef.util import build_deterministic_objects, process_result
from ingest.sources.pipeline import run_pipeline as _run_pipeline

_KEY_COLUMNS = ["date", "region_id", "type_id"]


def _build_cache_objects(start_date: date, end_date: date) -> list[CacheObject]:
    return build_deterministic_objects(
        start_date,
        end_date,
        url_prefix="market-history",
        filename_prefix="market-history-",
    )


def run_pipeline(config: EverefCliConfig) -> int:
    return _run_pipeline(
        dataset_name="market-history",
        update_mode=UpdateMode.MUTABLE,
        objects=_build_cache_objects(config.start_date, config.end_date),
        config=config,
        process_one=lambda r, w: process_result(
            r,
            w,
            table_key=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            key_columns=_KEY_COLUMNS,
        ),
    )
