"""Pipeline helpers for Everef ingestion."""

from __future__ import annotations

from typing import Any

import dlt

from ingest import activate_dlt_workspace
from ingest.clients.everef import BASE_URL
from ingest.cli_config import EverefMarketHistoryCliConfig
from ingest.input_sources import RAW_CACHE_INPUT_SOURCE, URL_INPUT_SOURCE
from ingest.publishers.ducklake import (
    build_destination_config as _build_destination_config,
)
from ingest.raw_files.config import resolve_raw_files_config
from ingest.raw_files.everef import acquire_everef_market_history_files
from ingest.sources.everef import everef_market_history_source


def run_everef_market_history_pipeline(
    config: EverefMarketHistoryCliConfig,
) -> Any:
    """Run the Everef market history source through a dlt pipeline."""
    activate_dlt_workspace()

    destination_config = _build_destination_config(
        config.destination,
        config.ducklake_name,
        config.ducklake_catalog,
        config.ducklake_storage,
        storage_target=config.storage.storage_target,
        data_root=config.storage.data_root,
    )

    pipeline = dlt.pipeline(
        pipeline_name=config.pipeline_name,
        destination=destination_config,
        dataset_name=config.dataset_name,
        dev_mode=config.dev_mode,
    )

    effective_input_source = (
        RAW_CACHE_INPUT_SOURCE if config.sync_raw else config.input_source
    )
    raw_config = None
    if config.sync_raw or effective_input_source == RAW_CACHE_INPUT_SOURCE:
        raw_config = resolve_raw_files_config(
            raw_root=config.raw_files.raw_root,
            ledger_url=config.raw_files.raw_ledger_url,
            max_copies_per_date=config.raw_files.raw_max_copies_per_date,
            storage_target=config.storage.storage_target,
            data_root=config.storage.data_root,
        )

    if config.sync_raw:
        assert raw_config is not None
        acquire_everef_market_history_files(
            config.date_range.start_date,
            config.date_range.end_date,
            base_url=config.base_url or BASE_URL,
            config=raw_config,
            check_headers=config.check_headers,
        )

    source_kwargs: dict[str, Any] = {}
    if config.base_url is not None:
        source_kwargs["base_url"] = config.base_url
    if config.chunksize is not None:
        source_kwargs["chunksize"] = config.chunksize

    if effective_input_source != URL_INPUT_SOURCE:
        source_kwargs["input_source"] = effective_input_source

    if effective_input_source == RAW_CACHE_INPUT_SOURCE:
        assert raw_config is not None
        source_kwargs["raw_root"] = str(raw_config.raw_root)
        source_kwargs["raw_ledger_url"] = raw_config.ledger_url

    return pipeline.run(
        everef_market_history_source(
            config.date_range.start_date,
            config.date_range.end_date,
            **source_kwargs,
        ),
        loader_file_format=config.loader_file_format,
    )
