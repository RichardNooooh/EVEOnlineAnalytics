"""Ingestion runtime helpers."""

from __future__ import annotations

import os
from pathlib import Path

DLT_STATE_DIR_ENV = "EVE_DLT_STATE_DIR"
DLT_DEFAULT_DATA_DIR_ENV = "EVE_DLT_DEFAULT_DATA_DIR"
DLT_DEFAULT_LOCAL_DIR_ENV = "EVE_DLT_DEFAULT_LOCAL_DIR"


def configure_runtime_environment() -> Path:
    """Anchor dlt project discovery and dlt state paths."""

    default_project_dir = Path(__file__).resolve().parent.parent
    project_dir = Path(
        os.environ.setdefault("DLT_PROJECT_DIR", str(default_project_dir))
    )

    state_dir = _configured_dlt_state_dir()
    if state_dir is not None:
        _set_explicit_runtime_path(
            "DLT_DATA_DIR",
            str(state_dir),
            DLT_DEFAULT_DATA_DIR_ENV,
        )
        _set_explicit_runtime_path(
            "DLT_LOCAL_DIR",
            str(state_dir / "local"),
            DLT_DEFAULT_LOCAL_DIR_ENV,
        )
        return project_dir

    _set_default_runtime_path(
        "DLT_DATA_DIR",
        str(_default_dlt_data_dir(project_dir)),
        DLT_DEFAULT_DATA_DIR_ENV,
    )
    _set_default_runtime_path(
        "DLT_LOCAL_DIR",
        str(project_dir / ".local"),
        DLT_DEFAULT_LOCAL_DIR_ENV,
    )

    return project_dir


def should_activate_dlt_workspace(project_dir: Path | None = None) -> bool:
    """Use repo-local workspace only when no explicit scratch override is set."""

    resolved_project_dir = project_dir or configure_runtime_environment()
    if _has_explicit_dlt_state_override(resolved_project_dir):
        return False
    return (resolved_project_dir / ".dlt" / ".workspace").exists()


def activate_dlt_workspace() -> Path:
    """Reload dlt into repo-local workspace context when enabled."""

    project_dir = configure_runtime_environment()
    if not should_activate_dlt_workspace(project_dir):
        return project_dir

    from dlt.common.runtime import run_context

    run_context.switch_context(str(project_dir), required="WorkspaceRunContext")
    return project_dir


def _configured_dlt_state_dir() -> Path | None:
    configured_state_dir = os.environ.get(DLT_STATE_DIR_ENV)
    if configured_state_dir is None:
        return None
    return Path(configured_state_dir)


def _default_dlt_data_dir(project_dir: Path) -> Path:
    return project_dir / ".dlt" / ".var"


def _set_default_runtime_path(env_var: str, value: str, marker_env_var: str) -> None:
    if env_var in os.environ:
        if os.environ.get(marker_env_var) == "1":
            os.environ[env_var] = value
            return

        os.environ.pop(marker_env_var, None)
        return

    os.environ[env_var] = value
    os.environ[marker_env_var] = "1"


def _set_explicit_runtime_path(env_var: str, value: str, marker_env_var: str) -> None:
    if env_var not in os.environ or os.environ.get(marker_env_var) == "1":
        os.environ[env_var] = value
    os.environ.pop(marker_env_var, None)


def _has_explicit_dlt_state_override(project_dir: Path) -> bool:
    if os.environ.get(DLT_STATE_DIR_ENV):
        return True

    configured_data_dir = os.environ.get("DLT_DATA_DIR")
    configured_local_dir = os.environ.get("DLT_LOCAL_DIR")
    data_dir_is_default = os.environ.get(DLT_DEFAULT_DATA_DIR_ENV) == "1"
    local_dir_is_default = os.environ.get(DLT_DEFAULT_LOCAL_DIR_ENV) == "1"

    return (configured_data_dir is not None and not data_dir_is_default) or (
        configured_local_dir is not None and not local_dir_is_default
    )
