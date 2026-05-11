"""DuckLake destination helpers for dlt publishers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from dlt.destinations import ducklake
from dlt.destinations.impl.ducklake.configuration import DuckLakeCredentials

from ingest.storage_config import (
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


def is_mounted_ducklake_storage(storage: str, *, data_root: str | None) -> bool:
    """Return whether storage is the DuckLake path under the mounted data root."""
    if storage == local_ducklake_storage():
        return False

    parsed_storage = urlparse(storage)
    if parsed_storage.scheme != "file":
        return False

    storage_path = Path(unquote(parsed_storage.path)).expanduser().resolve()
    mounted_storage_path = (
        mounted_data_root_path(resolve_mounted_data_root(data_root))
        / "ducklake/everef/market_history"
    )
    return storage_path == mounted_storage_path


def validate_mounted_ducklake_catalog(
    catalog: str,
    *,
    storage: str,
    storage_target: str,
    data_root: str | None,
) -> None:
    """Reject local sqlite catalogs for mounted DuckLake storage."""
    if not catalog.startswith("sqlite:///"):
        return
    if storage_target != MOUNTED_STORAGE_TARGET and not is_mounted_ducklake_storage(
        storage,
        data_root=data_root,
    ):
        return

    msg = (
        "mounted DuckLake storage requires a non-local catalog such as PostgreSQL; "
        f"set ducklake_catalog or {DUCKLAKE_CATALOG_ENV_VAR} to a PostgreSQL catalog URL"
    )
    raise ValueError(msg)


def build_destination_config(
    destination: str = "ducklake",
    ducklake_name: str | None = None,
    ducklake_catalog: str | None = None,
    ducklake_storage: str | None = None,
    *,
    storage_target: str = LOCAL_STORAGE_TARGET,
    data_root: str | None = None,
    credentials_factory: Callable[..., Any] | None = None,
    destination_factory: Callable[..., Any] | None = None,
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
    validate_mounted_ducklake_catalog(
        catalog,
        storage=storage,
        storage_target=storage_target,
        data_root=data_root,
    )

    ensure_local_ducklake_paths(catalog, storage)

    if credentials_factory is None:
        credentials_factory = DuckLakeCredentials
    if destination_factory is None:
        destination_factory = ducklake

    credentials = credentials_factory(
        name,
        catalog=catalog,
        storage=storage,
    )
    return destination_factory(credentials=credentials)
