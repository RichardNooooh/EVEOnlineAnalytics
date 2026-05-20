"""Ingestion runtime helpers."""

from __future__ import annotations

import os
from pathlib import Path

DLT_STATE_DIR_ENV = "EVE_DLT_STATE_DIR"


def configure_runtime_environment() -> Path:
    """Anchor dlt project discovery and optional scratch paths."""

    default_project_dir = Path(__file__).resolve().parent.parent
    project_dir = Path(
        os.environ.setdefault("DLT_PROJECT_DIR", str(default_project_dir))
    )

    state_dir = _configured_dlt_state_dir()
    if state_dir is not None:
        os.environ.setdefault("DLT_DATA_DIR", str(state_dir))
        os.environ.setdefault("DLT_LOCAL_DIR", str(state_dir / "local"))

    return project_dir


def should_activate_dlt_workspace(project_dir: Path | None = None) -> bool:
    """Use repo-local workspace only when no explicit scratch override is set."""

    if _has_explicit_dlt_state_override():
        return False

    resolved_project_dir = project_dir or configure_runtime_environment()
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


def _has_explicit_dlt_state_override() -> bool:
    return any(
        os.environ.get(env_var)
        for env_var in (DLT_STATE_DIR_ENV, "DLT_DATA_DIR", "DLT_LOCAL_DIR")
    )
