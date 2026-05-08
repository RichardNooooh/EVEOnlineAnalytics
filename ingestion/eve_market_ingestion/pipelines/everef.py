"""Pipeline helpers for Everef ingestion."""

from __future__ import annotations

from datetime import date
import os
from typing import Any

import dlt
from dlt.destinations import filesystem

from eve_market_ingestion.sources.everef_market_history import (
    everef_market_history_source,
)

BUCKET_URL_ENV_VAR = "EVE_MARKET_INGESTION_BUCKET_URL"


def build_destination_config(destination: str, bucket_url: str | None = None) -> str | Any:
    """Build a dlt destination config, resolving filesystem storage explicitly."""
    if destination != "filesystem":
        return destination

    resolved_bucket_url = bucket_url or os.getenv(BUCKET_URL_ENV_VAR)
    if resolved_bucket_url is None:
        msg = (
            "filesystem destination requires --bucket-url or "
            f"{BUCKET_URL_ENV_VAR}"
        )
        raise ValueError(msg)

    return filesystem(bucket_url=resolved_bucket_url)


def run_everef_market_history_pipeline(
    start_date: str | date,
    end_date: str | date,
    *,
    pipeline_name: str = "everef_market_history",
    dataset_name: str = "everef_market_history",
    destination: str = "filesystem",
    bucket_url: str | None = None,
    base_url: str | None = None,
    chunksize: int | None = None,
    loader_file_format: str = "parquet",
    dev_mode: bool = False,
) -> Any:
    """Run the Everef market history source through a dlt pipeline."""
    destination_config = build_destination_config(destination, bucket_url)

    pipeline = dlt.pipeline(
        pipeline_name=pipeline_name,
        destination=destination_config,
        dataset_name=dataset_name,
        dev_mode=dev_mode,
    )

    source_kwargs: dict[str, Any] = {}
    if base_url is not None:
        source_kwargs["base_url"] = base_url
    if chunksize is not None:
        source_kwargs["chunksize"] = chunksize

    return pipeline.run(
        everef_market_history_source(start_date, end_date, **source_kwargs),
        loader_file_format=loader_file_format,
    )
