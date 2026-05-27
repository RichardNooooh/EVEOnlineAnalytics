"""Path-building utilities for raw object storage."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from ingest.cache.models import BaseFetchPlan, UpdateMode


def build_temp_path(*, raw_root: Path, source_name: str) -> Path:
    source_name = validate_path_segment(source_name, field_name="source_name")
    return raw_root / source_name / ".tmp" / f"{uuid4().hex}.download"


def build_final_path(
    *,
    raw_root: Path,
    plan: BaseFetchPlan,
    fetched_at: datetime,
    sha256: str,
) -> Path:
    if plan.update_mode is UpdateMode.SNAPSHOT:
        return build_snapshot_path(raw_root=raw_root, plan=plan)

    source_name = validate_path_segment(plan.ref.source_name, field_name="source_name")
    dataset_name = validate_path_segment(plan.ref.dataset_name, field_name="dataset_name")

    basename = Path(plan.source_relative_path).name or f"{dataset_name}.bin"
    timestamp = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    return (
        raw_root
        / source_name
        / dataset_name
        / "objects"
        / plan.ref.identity_hash
        / f"{timestamp}__{sha256[:12]}__{uuid4().hex[:8]}__{basename}"
    )


def build_snapshot_path(*, raw_root: Path, plan: BaseFetchPlan) -> Path:
    source_name = validate_path_segment(plan.ref.source_name, field_name="source_name")
    return raw_root / source_name / Path(plan.source_relative_path)


def detect_storage_encoding(path: Path) -> str:
    suffixes = [suffix.lstrip(".") for suffix in path.suffixes]
    if not suffixes:
        return "raw"
    return ".".join(suffixes)


def validate_path_segment(value: str, *, field_name: str) -> str:
    if not value or value in {".", ".."}:
        raise ValueError(f"{field_name} must be a safe non-empty path segment")
    if "/" in value or "\\" in value:
        raise ValueError(f"{field_name} must not contain path separators")
    return value
