"""Pipeline helpers for Everef ingestion."""

from __future__ import annotations

from datetime import date
import os
from pathlib import Path
from typing import Any

import dlt
from dlt.destinations import filesystem

from eve_market_ingestion.sources.everef_market_history import (
    everef_market_history_source,
)

BUCKET_URL_ENV_VAR = "EVE_MARKET_INGESTION_BUCKET_URL"
DATA_ROOT_ENV_VAR = "EVE_MARKET_DATA_ROOT"
LOCAL_STORAGE_TARGET = "local"
MOUNTED_STORAGE_TARGET = "mounted"
STORAGE_TARGETS = (LOCAL_STORAGE_TARGET, MOUNTED_STORAGE_TARGET)
DEFAULT_MOUNTED_DATA_ROOT = "/opt/eve-market/data"


def local_bucket_url() -> str:
    """Return the repo-local filesystem bucket URL independent of cwd."""
    ingestion_root = Path(__file__).resolve().parents[2]
    return (ingestion_root / ".local/dlt-staging/everef/market_history").as_uri()


def mounted_bucket_url(data_root: str) -> str:
    """Return the mounted filesystem bucket URL under a configured data root."""
    if not data_root.strip():
        msg = "data_root must not be empty"
        raise ValueError(msg)
    return (
        Path(data_root).expanduser().resolve() / "dlt-staging/everef/market_history"
    ).as_uri()


def resolve_mounted_data_root(data_root: str | None = None) -> str:
    """Resolve mounted data root by explicit, env, then default precedence."""
    if data_root is not None:
        if not data_root.strip():
            msg = "data_root must not be empty"
            raise ValueError(msg)
        return data_root

    env_data_root = os.getenv(DATA_ROOT_ENV_VAR)
    if env_data_root is not None:
        if not env_data_root.strip():
            msg = f"{DATA_ROOT_ENV_VAR} must not be empty"
            raise ValueError(msg)
        return env_data_root

    return DEFAULT_MOUNTED_DATA_ROOT


def bucket_url_for_storage_target(
    storage_target: str,
    data_root: str | None = None,
) -> str:
    """Resolve a named storage target to its default filesystem bucket URL."""
    if storage_target == LOCAL_STORAGE_TARGET:
        return local_bucket_url()
    if storage_target == MOUNTED_STORAGE_TARGET:
        return mounted_bucket_url(resolve_mounted_data_root(data_root))

    msg = f"storage_target must be one of {', '.join(STORAGE_TARGETS)}"
    raise ValueError(msg)


def resolve_bucket_url(
    bucket_url: str | None = None,
    *,
    storage_target: str = LOCAL_STORAGE_TARGET,
    data_root: str | None = None,
) -> str:
    """Resolve filesystem bucket URL by explicit, env, target, then local precedence."""
    if bucket_url is not None:
        if not bucket_url.strip():
            msg = "bucket_url must not be empty"
            raise ValueError(msg)
        return bucket_url

    env_bucket_url = os.getenv(BUCKET_URL_ENV_VAR)
    if env_bucket_url is not None:
        if not env_bucket_url.strip():
            msg = f"{BUCKET_URL_ENV_VAR} must not be empty"
            raise ValueError(msg)
        return env_bucket_url

    return bucket_url_for_storage_target(storage_target, data_root)


def build_destination_config(
    destination: str,
    bucket_url: str | None = None,
    *,
    storage_target: str = LOCAL_STORAGE_TARGET,
    data_root: str | None = None,
) -> str | Any:
    """Build a dlt destination config, resolving filesystem storage explicitly."""
    if destination != "filesystem":
        return destination

    return filesystem(
        bucket_url=resolve_bucket_url(
            bucket_url,
            storage_target=storage_target,
            data_root=data_root,
        )
    )


def run_everef_market_history_pipeline(
    start_date: str | date,
    end_date: str | date,
    *,
    pipeline_name: str = "everef_market_history",
    dataset_name: str = "everef_market_history",
    destination: str = "filesystem",
    bucket_url: str | None = None,
    storage_target: str = LOCAL_STORAGE_TARGET,
    data_root: str | None = None,
    base_url: str | None = None,
    chunksize: int | None = None,
    loader_file_format: str = "parquet",
    dev_mode: bool = False,
) -> Any:
    """Run the Everef market history source through a dlt pipeline."""
    destination_config = build_destination_config(
        destination,
        bucket_url,
        storage_target=storage_target,
        data_root=data_root,
    )

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
