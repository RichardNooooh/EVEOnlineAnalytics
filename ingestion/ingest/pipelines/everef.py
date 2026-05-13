"""Pipeline helpers for Everef ingestion."""

from __future__ import annotations

from datetime import date
from typing import Any

import dlt

from ingest.clients.everef import BASE_URL
from ingest.publishers.ducklake import (
    build_destination_config as _build_destination_config,
)
from ingest.raw_files.config import resolve_raw_files_config
from ingest.raw_files.everef import acquire_everef_market_history_files
from ingest.sources.everef import (
    RAW_CACHE_INPUT_SOURCE,
    URL_INPUT_SOURCE,
    everef_market_history_source,
)
from ingest.storage_config import LOCAL_STORAGE_TARGET


def run_everef_market_history_pipeline(
    start_date: str | date,
    end_date: str | date,
    *,
    pipeline_name: str = "everef_market_history",
    dataset_name: str = "everef_market_history",
    destination: str = "ducklake",
    ducklake_name: str | None = None,
    ducklake_catalog: str | None = None,
    ducklake_storage: str | None = None,
    storage_target: str = LOCAL_STORAGE_TARGET,
    data_root: str | None = None,
    base_url: str | None = None,
    chunksize: int | None = None,
    input_source: str = URL_INPUT_SOURCE,
    sync_raw: bool = False,
    raw_root: str | None = None,
    raw_ledger_url: str | None = None,
    raw_max_copies_per_date: int | str | None = None,
    loader_file_format: str = "parquet",
    dev_mode: bool = False,
) -> Any:
    """Run the Everef market history source through a dlt pipeline."""
    destination_config = _build_destination_config(
        destination,
        ducklake_name,
        ducklake_catalog,
        ducklake_storage,
        storage_target=storage_target,
        data_root=data_root,
    )

    pipeline = dlt.pipeline(
        pipeline_name=pipeline_name,
        destination=destination_config,
        dataset_name=dataset_name,
        dev_mode=dev_mode,
    )

    effective_input_source = RAW_CACHE_INPUT_SOURCE if sync_raw else input_source
    raw_config = None
    if sync_raw or effective_input_source == RAW_CACHE_INPUT_SOURCE:
        raw_config = resolve_raw_files_config(
            raw_root=raw_root,
            ledger_url=raw_ledger_url,
            max_copies_per_date=raw_max_copies_per_date,
            storage_target=storage_target,
            data_root=data_root,
        )

    if sync_raw:
        assert raw_config is not None
        acquire_everef_market_history_files(
            start_date,
            end_date,
            base_url=base_url or BASE_URL,
            config=raw_config,
        )

    source_kwargs: dict[str, Any] = {}
    if base_url is not None:
        source_kwargs["base_url"] = base_url
    if chunksize is not None:
        source_kwargs["chunksize"] = chunksize

    if effective_input_source != URL_INPUT_SOURCE:
        source_kwargs["input_source"] = effective_input_source

    if effective_input_source == RAW_CACHE_INPUT_SOURCE:
        assert raw_config is not None
        source_kwargs["raw_root"] = str(raw_config.raw_root)
        source_kwargs["raw_ledger_url"] = raw_config.ledger_url

    return pipeline.run(
        everef_market_history_source(start_date, end_date, **source_kwargs),
        loader_file_format=loader_file_format,
    )
