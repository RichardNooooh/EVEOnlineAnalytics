"""Raw source-file cache configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ingest.storage_config import (
    DATA_ROOT_ENV_VAR as DATA_ROOT_ENV_VAR,
)
from ingest.storage_config import (
    DEFAULT_MOUNTED_DATA_ROOT as DEFAULT_MOUNTED_DATA_ROOT,
)
from ingest.storage_config import (
    LOCAL_STORAGE_TARGET,
    MOUNTED_STORAGE_TARGET,
    STORAGE_TARGETS,
    ingestion_root,
    mounted_data_root_path,
    resolve_mounted_data_root,
)

RAW_FILES_ROOT_ENV_VAR = "EVE_MARKET_RAW_FILES_ROOT"
RAW_FILES_LEDGER_URL_ENV_VAR = "EVE_MARKET_RAW_FILES_LEDGER_URL"
RAW_FILES_MAX_COPIES_PER_DATE_ENV_VAR = "EVE_MARKET_RAW_FILES_MAX_COPIES_PER_DATE"
DEFAULT_MAX_COPIES_PER_DATE = 5


@dataclass(frozen=True)
class RawFilesConfig:
    """Resolved raw-file cache and ledger URL."""

    raw_root: Path
    ledger_url: str
    max_copies_per_date: int = DEFAULT_MAX_COPIES_PER_DATE


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
    ledger_url: str | None = None,
    max_copies_per_date: int | str | None = None,
    storage_target: str = LOCAL_STORAGE_TARGET,
    data_root: str | None = None,
) -> RawFilesConfig:
    """Resolve raw-file cache root and acquisition ledger URL."""
    resolved_root = _resolve_optional_path(
        raw_root,
        env_var=RAW_FILES_ROOT_ENV_VAR,
        default=raw_files_root_for_target(storage_target, data_root),
        value_name="raw_root",
    )
    resolved_ledger_url = _resolve_ledger_url(
        ledger_url=ledger_url,
        default_ledger_path=resolved_root / "raw_files.sqlite",
    )
    resolved_max_copies = _resolve_max_copies_per_date(max_copies_per_date)
    return RawFilesConfig(
        raw_root=resolved_root,
        ledger_url=resolved_ledger_url,
        max_copies_per_date=resolved_max_copies,
    )


def sqlite_ledger_url(ledger_path: Path) -> str:
    """Return SQLite URL for an absolute database path."""
    return f"sqlite:///{ledger_path.expanduser().resolve()}"


def sqlite_path_from_ledger_url(ledger_url: str) -> Path:
    """Return SQLite path from ledger URL."""
    if ledger_url.startswith("sqlite:///"):
        return Path(ledger_url.removeprefix("sqlite://")).expanduser().resolve()
    msg = "ledger_url must be a SQLite URL"
    raise ValueError(msg)


def _resolve_ledger_url(
    *,
    ledger_url: str | None,
    default_ledger_path: Path,
) -> str:
    if ledger_url is not None:
        return _validate_ledger_url(ledger_url, "ledger_url")

    env_ledger_url = os.getenv(RAW_FILES_LEDGER_URL_ENV_VAR)
    if env_ledger_url is not None:
        return _validate_ledger_url(env_ledger_url, RAW_FILES_LEDGER_URL_ENV_VAR)

    return sqlite_ledger_url(default_ledger_path)


def _validate_ledger_url(value: str, value_name: str) -> str:
    if not value.strip():
        msg = f"{value_name} must not be empty"
        raise ValueError(msg)
    if not urlparse(value).scheme:
        msg = f"{value_name} must be a sqlite, postgres, or postgresql URL"
        raise ValueError(msg)
    return value


def _resolve_max_copies_per_date(explicit_value: int | str | None) -> int:
    if explicit_value is not None:
        return _parse_max_copies_per_date(explicit_value, "max_copies_per_date")

    env_value = os.getenv(RAW_FILES_MAX_COPIES_PER_DATE_ENV_VAR)
    if env_value is not None:
        return _parse_max_copies_per_date(
            env_value,
            RAW_FILES_MAX_COPIES_PER_DATE_ENV_VAR,
        )

    return DEFAULT_MAX_COPIES_PER_DATE


def _parse_max_copies_per_date(value: int | str, value_name: str) -> int:
    if isinstance(value, int):
        parsed = value
    else:
        if not value.strip():
            msg = f"{value_name} must not be empty"
            raise ValueError(msg)
        try:
            parsed = int(value)
        except ValueError as exc:
            msg = f"{value_name} must be an integer greater than or equal to 0"
            raise ValueError(msg) from exc

    if parsed < 0:
        msg = f"{value_name} must be greater than or equal to 0"
        raise ValueError(msg)
    return parsed


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
