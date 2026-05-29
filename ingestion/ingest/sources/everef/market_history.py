from __future__ import annotations

from datetime import date

from ingest.cache import CacheObject, UpdateMode
from ingest.cli.config import EverefCliConfig
from ingest.publishers.ducklake import RawDuckLakeTable
from ingest.sources.everef.util import EVEREF_BASE, process_result
from ingest.sources.pipeline import run_pipeline as _run_pipeline
from ingest.util import iter_dates

_KEY_COLUMNS = ["date", "region_id", "type_id"]


def _build_cache_objects(start_date: date, end_date: date) -> list[CacheObject]:
    return [
        CacheObject(
            source_url=(f"{EVEREF_BASE}/market-history/{d.year}/market-history-{d.isoformat()}.csv.bz2"),
            identity_key={"source_date": d.isoformat()},
        )
        for d in iter_dates(start_date, end_date)
    ]


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
            key_columns=_KEY_COLUMNS,
        ),
    )
