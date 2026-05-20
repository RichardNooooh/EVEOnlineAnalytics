"""Raw source-file cache configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ingest.storage_config import (
    LOCAL_STORAGE_TARGET,
    MOUNTED_STORAGE_TARGET,
    STORAGE_TARGETS,
    ingestion_root,
    mounted_data_root_path,
    resolve_mounted_data_root,
    resolve_optional_config_value,
)

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
    resolved_root_value = resolve_optional_config_value(
        raw_root,
        value_name="raw_root",
    )
    if resolved_root_value is not None:
        resolved_root = Path(resolved_root_value).expanduser().resolve()
    else:
        resolved_root = raw_files_root_for_target(storage_target, data_root)

    resolved_ledger_url = _resolve_ledger_url(
        ledger_url=ledger_url,
        default_ledger_path=resolved_root / "raw_files.sqlite",
        requires_explicit_ledger=_requires_explicit_ledger(
            resolved_root,
            storage_target=storage_target,
            data_root=data_root,
        ),
    )
    if max_copies_per_date is not None:
        resolved_max_copies = _parse_max_copies_per_date(
            max_copies_per_date,
            "max_copies_per_date",
        )
    else:
        resolved_max_copies = DEFAULT_MAX_COPIES_PER_DATE

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
    requires_explicit_ledger: bool,
) -> str:
    resolved_ledger_url = resolve_optional_config_value(
        ledger_url,
        value_name="ledger_url",
    )
    if resolved_ledger_url is not None:
        return _validate_ledger_url(resolved_ledger_url, "ledger_url")

    if requires_explicit_ledger:
        msg = (
            "mounted raw-file storage requires an explicit ledger URL such as "
            "PostgreSQL; set ledger_url"
        )
        raise ValueError(msg)

    return sqlite_ledger_url(default_ledger_path)


def _requires_explicit_ledger(
    raw_root: Path,
    *,
    storage_target: str,
    data_root: str | None,
) -> bool:
    if storage_target != MOUNTED_STORAGE_TARGET:
        return False
    mounted_root = mounted_data_root_path(resolve_mounted_data_root(data_root))
    return raw_root == mounted_root or raw_root.is_relative_to(mounted_root)


def _validate_ledger_url(value: str, value_name: str) -> str:
    if not value.strip():
        msg = f"{value_name} must not be empty"
        raise ValueError(msg)
    if not urlparse(value).scheme:
        msg = f"{value_name} must be a sqlite, postgres, or postgresql URL"
        raise ValueError(msg)
    return value


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
