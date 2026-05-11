"""Pipeline helpers for Everef ingestion."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import dlt
from dlt.destinations import ducklake
from dlt.destinations.impl.ducklake.configuration import DuckLakeCredentials

from eve_market_ingestion.sources.everef_market_history import (
    everef_market_history_source,
)

DATA_ROOT_ENV_VAR = "EVE_MARKET_DATA_ROOT"
DUCKLAKE_NAME_ENV_VAR = "EVE_MARKET_DUCKLAKE_NAME"
DUCKLAKE_CATALOG_ENV_VAR = "EVE_MARKET_DUCKLAKE_CATALOG"
DUCKLAKE_STORAGE_ENV_VAR = "EVE_MARKET_DUCKLAKE_STORAGE"
DEFAULT_DUCKLAKE_NAME = "eve_market"
LOCAL_STORAGE_TARGET = "local"
MOUNTED_STORAGE_TARGET = "mounted"
STORAGE_TARGETS = (LOCAL_STORAGE_TARGET, MOUNTED_STORAGE_TARGET)
DEFAULT_MOUNTED_DATA_ROOT = "/opt/eve-market/data"


def local_ducklake_root() -> Path:
    """Return the repo-local DuckLake root independent of cwd."""
    ingestion_root = Path(__file__).resolve().parents[2]
    return ingestion_root / ".local/ducklake/everef_market_history"


def local_ducklake_catalog() -> str:
    """Return the repo-local DuckLake sqlite catalog URL."""
    return f"sqlite:///{local_ducklake_root() / 'lake_catalog.sqlite'}"


def local_ducklake_storage() -> str:
    """Return the repo-local DuckLake file storage URL."""
    return (local_ducklake_root() / "files").as_uri()


def mounted_ducklake_storage(data_root: str) -> str:
    """Return the mounted DuckLake file storage URL under a configured data root."""
    if not data_root.strip():
        msg = "data_root must not be empty"
        raise ValueError(msg)
    return (
        Path(data_root).expanduser().resolve() / "ducklake/everef/market_history"
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


def resolve_config_value(
    explicit_value: str | None,
    *,
    env_var: str,
    default_value: str,
    value_name: str,
) -> str:
    """Resolve config by explicit, env, then default precedence."""
    if explicit_value is not None:
        if not explicit_value.strip():
            msg = f"{value_name} must not be empty"
            raise ValueError(msg)
        return explicit_value

    env_value = os.getenv(env_var)
    if env_value is not None:
        if not env_value.strip():
            msg = f"{env_var} must not be empty"
            raise ValueError(msg)
        return env_value

    return default_value


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

    credentials = DuckLakeCredentials(
        resolve_config_value(
            ducklake_name,
            env_var=DUCKLAKE_NAME_ENV_VAR,
            default_value=DEFAULT_DUCKLAKE_NAME,
            value_name="ducklake_name",
        ),
        catalog=resolve_config_value(
            ducklake_catalog,
            env_var=DUCKLAKE_CATALOG_ENV_VAR,
            default_value=local_ducklake_catalog(),
            value_name="ducklake_catalog",
        ),
        storage=resolve_ducklake_storage(
            ducklake_storage,
            storage_target=storage_target,
            data_root=data_root,
        ),
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

    source_kwargs: dict[str, Any] = {}
    if base_url is not None:
        source_kwargs["base_url"] = base_url
    if chunksize is not None:
        source_kwargs["chunksize"] = chunksize

    return pipeline.run(
        everef_market_history_source(start_date, end_date, **source_kwargs),
        loader_file_format=loader_file_format,
    )
