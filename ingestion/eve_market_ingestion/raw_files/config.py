"""Raw source-file cache configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from eve_market_ingestion.storage_config import (
    DATA_ROOT_ENV_VAR as DATA_ROOT_ENV_VAR,
    DEFAULT_MOUNTED_DATA_ROOT as DEFAULT_MOUNTED_DATA_ROOT,
    LOCAL_STORAGE_TARGET,
    MOUNTED_STORAGE_TARGET,
    STORAGE_TARGETS,
    ingestion_root,
    mounted_data_root_path,
    resolve_mounted_data_root,
)

RAW_FILES_ROOT_ENV_VAR = "EVE_MARKET_RAW_FILES_ROOT"
RAW_FILES_DB_ENV_VAR = "EVE_MARKET_RAW_FILES_DB"


@dataclass(frozen=True)
class RawFilesConfig:
    """Resolved raw-file cache and SQLite ledger paths."""

    raw_root: Path
    db_path: Path


def local_raw_files_root() -> Path:
    """Return the repo-local raw source-file cache root."""
    return ingestion_root() / ".local/raw"


def mounted_raw_files_root(data_root: str) -> Path:
    """Return the mounted raw source-file cache root under data root."""
    return mounted_data_root_path(data_root) / "raw"


def raw_files_root_for_target(
    storage_target: str,
    data_root: str | None = None,
) -> Path:
    """Resolve a named storage target to a raw source-file cache root."""
    if storage_target == LOCAL_STORAGE_TARGET:
        return local_raw_files_root()
    if storage_target == MOUNTED_STORAGE_TARGET:
        return mounted_raw_files_root(resolve_mounted_data_root(data_root))

    msg = f"storage_target must be one of {', '.join(STORAGE_TARGETS)}"
    raise ValueError(msg)


def resolve_raw_files_config(
    *,
    raw_root: str | None = None,
    db_path: str | None = None,
    storage_target: str = LOCAL_STORAGE_TARGET,
    data_root: str | None = None,
) -> RawFilesConfig:
    """Resolve raw-file cache root and SQLite ledger path."""
    resolved_root = _resolve_optional_path(
        raw_root,
        env_var=RAW_FILES_ROOT_ENV_VAR,
        default=raw_files_root_for_target(storage_target, data_root),
        value_name="raw_root",
    )
    resolved_db = _resolve_optional_path(
        db_path,
        env_var=RAW_FILES_DB_ENV_VAR,
        default=resolved_root / "raw_files.sqlite",
        value_name="db_path",
    )
    return RawFilesConfig(raw_root=resolved_root, db_path=resolved_db)


def _resolve_optional_path(
    explicit_value: str | None,
    *,
    env_var: str,
    default: Path,
    value_name: str,
) -> Path:
    if explicit_value is not None:
        if not explicit_value.strip():
            msg = f"{value_name} must not be empty"
            raise ValueError(msg)
        return Path(explicit_value).expanduser().resolve()

    env_value = os.getenv(env_var)
    if env_value is not None:
        if not env_value.strip():
            msg = f"{env_var} must not be empty"
            raise ValueError(msg)
        return Path(env_value).expanduser().resolve()

    return default
