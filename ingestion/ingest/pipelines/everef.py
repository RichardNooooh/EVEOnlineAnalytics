"""Pipeline helpers for Everef ingestion."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import dlt
from dlt.destinations import ducklake
from dlt.destinations.impl.ducklake.configuration import DuckLakeCredentials

from ingest.everef_files import BASE_URL
from ingest.raw_files.config import resolve_raw_files_config
from ingest.raw_files.everef import acquire_everef_market_history_files
from ingest.sources.everef import (
    RAW_CACHE_INPUT_SOURCE,
    URL_INPUT_SOURCE,
    everef_market_history_source,
)
from ingest.storage_config import (
    DATA_ROOT_ENV_VAR as DATA_ROOT_ENV_VAR,
    DEFAULT_MOUNTED_DATA_ROOT as DEFAULT_MOUNTED_DATA_ROOT,
    LOCAL_STORAGE_TARGET,
    MOUNTED_STORAGE_TARGET,
    STORAGE_TARGETS,
    ingestion_root,
    mounted_data_root_path,
    resolve_config_value,
    resolve_mounted_data_root,
)

DUCKLAKE_NAME_ENV_VAR = "EVE_MARKET_DUCKLAKE_NAME"
DUCKLAKE_CATALOG_ENV_VAR = "EVE_MARKET_DUCKLAKE_CATALOG"
DUCKLAKE_STORAGE_ENV_VAR = "EVE_MARKET_DUCKLAKE_STORAGE"
DEFAULT_DUCKLAKE_NAME = "eve_market"


def local_ducklake_root() -> Path:
    """Return the repo-local DuckLake root independent of cwd."""
    return ingestion_root() / ".local/ducklake/everef_market_history"


def local_ducklake_catalog() -> str:
    """Return the repo-local DuckLake sqlite catalog URL."""
    return f"sqlite:///{local_ducklake_root() / 'lake_catalog.sqlite'}"


def local_ducklake_storage() -> str:
    """Return the repo-local DuckLake file storage URL."""
    return (local_ducklake_root() / "files").as_uri()


def ensure_local_ducklake_paths(catalog: str, storage: str) -> None:
    """Create repo-local DuckLake paths when local defaults are in use."""
    root = local_ducklake_root()
    if catalog == local_ducklake_catalog():
        root.mkdir(parents=True, exist_ok=True)
    if storage == local_ducklake_storage():
        (root / "files").mkdir(parents=True, exist_ok=True)


def mounted_ducklake_storage(data_root: str) -> str:
    """Return the mounted DuckLake file storage URL under a configured data root."""
    return (
        mounted_data_root_path(data_root) / "ducklake/everef/market_history"
    ).as_uri()


def ducklake_storage_for_target(
    storage_target: str,
    data_root: str | None = None,
) -> str:
    """Resolve a named storage target to its default DuckLake storage URL."""
    if storage_target == LOCAL_STORAGE_TARGET:
        return local_ducklake_storage()
    if storage_target == MOUNTED_STORAGE_TARGET:
        return mounted_ducklake_storage(resolve_mounted_data_root(data_root))

    msg = f"storage_target must be one of {', '.join(STORAGE_TARGETS)}"
    raise ValueError(msg)


def resolve_ducklake_storage(
    ducklake_storage: str | None,
    *,
    storage_target: str,
    data_root: str | None,
) -> str:
    """Resolve DuckLake storage by explicit, env, target, then local precedence."""
    if ducklake_storage is not None:
        if not ducklake_storage.strip():
            msg = "ducklake_storage must not be empty"
            raise ValueError(msg)
        return ducklake_storage

    env_storage = os.getenv(DUCKLAKE_STORAGE_ENV_VAR)
    if env_storage is not None:
        if not env_storage.strip():
            msg = f"{DUCKLAKE_STORAGE_ENV_VAR} must not be empty"
            raise ValueError(msg)
        return env_storage

    return ducklake_storage_for_target(storage_target, data_root)


def build_destination_config(
    destination: str = "ducklake",
    ducklake_name: str | None = None,
    ducklake_catalog: str | None = None,
    ducklake_storage: str | None = None,
    *,
    storage_target: str = LOCAL_STORAGE_TARGET,
    data_root: str | None = None,
) -> str | Any:
    """Build a dlt destination config, keeping non-DuckLake strings as escape hatch."""
    if destination != "ducklake":
        return destination

    name = resolve_config_value(
        ducklake_name,
        env_var=DUCKLAKE_NAME_ENV_VAR,
        default_value=DEFAULT_DUCKLAKE_NAME,
        value_name="ducklake_name",
    )
    catalog = resolve_config_value(
        ducklake_catalog,
        env_var=DUCKLAKE_CATALOG_ENV_VAR,
        default_value=local_ducklake_catalog(),
        value_name="ducklake_catalog",
    )
    storage = resolve_ducklake_storage(
        ducklake_storage,
        storage_target=storage_target,
        data_root=data_root,
    )

    ensure_local_ducklake_paths(catalog, storage)

    credentials = DuckLakeCredentials(
        name,
        catalog=catalog,
        storage=storage,
    )
    return ducklake(credentials=credentials)


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
    raw_ledger_db: str | None = None,
    loader_file_format: str = "parquet",
    dev_mode: bool = False,
) -> Any:
    """Run the Everef market history source through a dlt pipeline."""
    destination_config = build_destination_config(
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

    if sync_raw:
        raw_config = resolve_raw_files_config(
            raw_root=raw_root,
            db_path=raw_ledger_db,
            storage_target=storage_target,
            data_root=data_root,
        )
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

    effective_input_source = RAW_CACHE_INPUT_SOURCE if sync_raw else input_source
    if effective_input_source != URL_INPUT_SOURCE:
        source_kwargs["input_source"] = effective_input_source

    if effective_input_source == RAW_CACHE_INPUT_SOURCE:
        source_kwargs["raw_root"] = raw_root
        source_kwargs["raw_ledger_db"] = raw_ledger_db
        source_kwargs["storage_target"] = storage_target
        source_kwargs["data_root"] = data_root

    return pipeline.run(
        everef_market_history_source(start_date, end_date, **source_kwargs),
        loader_file_format=loader_file_format,
    )
