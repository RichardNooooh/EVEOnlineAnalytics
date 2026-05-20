"""Shared ingestion storage configuration helpers."""

from __future__ import annotations

from pathlib import Path

LOCAL_STORAGE_TARGET = "local"
MOUNTED_STORAGE_TARGET = "mounted"
STORAGE_TARGETS = (LOCAL_STORAGE_TARGET, MOUNTED_STORAGE_TARGET)
DEFAULT_MOUNTED_DATA_ROOT = "/opt/eve-market/data"


def ingestion_root() -> Path:
    """Return the standalone ingestion project root."""
    return Path(__file__).resolve().parents[1]


def mounted_data_root_path(data_root: str) -> Path:
    """Return a validated mounted data root path."""
    if not data_root.strip():
        msg = "data_root must not be empty"
        raise ValueError(msg)
    return Path(data_root).expanduser().resolve()


def resolve_mounted_data_root(data_root: str | None = None) -> str:
    """Resolve mounted data root by explicit value or built-in default."""
    return resolve_config_value(
        data_root,
        default_value=DEFAULT_MOUNTED_DATA_ROOT,
        value_name="data_root",
    )


def resolve_optional_config_value(
    explicit_value: str | None,
    value_name: str,
) -> str | None:
    """Resolve optional config from explicit value only."""
    if explicit_value is not None:
        if not explicit_value.strip():
            msg = f"{value_name} must not be empty"
            raise ValueError(msg)
        return explicit_value

    return None


def resolve_config_value(
    explicit_value: str | None,
    default_value: str,
    value_name: str,
) -> str:
    """Resolve config by explicit value or built-in default."""
    resolved_value = resolve_optional_config_value(
        explicit_value,
        value_name=value_name,
    )
    if resolved_value is not None:
        return resolved_value
    return default_value
