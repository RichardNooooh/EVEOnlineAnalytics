"""Shared ingestion storage configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path

DATA_ROOT_ENV_VAR = "EVE_MARKET_DATA_ROOT"
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
    """Resolve mounted data root by explicit, env, then default precedence."""
    return resolve_config_value(
        data_root,
        env_var=DATA_ROOT_ENV_VAR,
        default_value=DEFAULT_MOUNTED_DATA_ROOT,
        value_name="data_root",
    )


def resolve_optional_config_value(
    explicit_value: str | None,
    *,
    env_var: str,
    value_name: str,
) -> str | None:
    """Resolve config by explicit, then env precedence with no default."""
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

    return None


def resolve_config_value(
    explicit_value: str | None,
    *,
    env_var: str,
    default_value: str,
    value_name: str,
) -> str:
    """Resolve config by explicit, env, then default precedence."""
    resolved_value = resolve_optional_config_value(
        explicit_value,
        env_var=env_var,
        value_name=value_name,
    )
    if resolved_value is not None:
        return resolved_value
    return default_value
