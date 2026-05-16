"""Generic raw source-file publishing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from ingest.raw_files.config import RawFilesConfig
from ingest.raw_files.downloader import download_with_sha256
from ingest.raw_files.models import (
    RawFileRecord,
    cached_record_is_valid,
    local_file_matches,
)
from ingest.raw_files.repository import RawFileRepository, create_raw_file_repository


@dataclass(frozen=True)
class RawFileSpec:
    """Description of one remote raw file and its cache layout."""

    source_name: str
    dataset_name: str
    source_date: str
    source_url: str
    file_name: str
    cache_relative_parts: tuple[str, ...]
    content_length: int | None = None
    last_modified: str | None = None
    etag: str | None = None
    source_row_count: int | None = None


def publish_raw_file(
    spec: RawFileSpec,
    *,
    config: RawFilesConfig,
    repository: RawFileRepository | None = None,
    http_client: Any = requests,
) -> RawFileRecord:
    """Download or reuse one raw source file and record acquisition metadata."""
    resolved_repository = repository or create_raw_file_repository(config.ledger_url)
    now = _utc_now()
    cached = resolved_repository.find_latest_success(
        source_name=spec.source_name,
        dataset_name=spec.dataset_name,
        source_date=spec.source_date,
        source_url=spec.source_url,
    )
    if cached is not None and _cached_record_matches(cached, spec):
        if cached.id is not None:
            resolved_repository.touch_checked(cached.id, now)
        _prune_old_copies(
            resolved_repository,
            source_name=spec.source_name,
            dataset_name=spec.dataset_name,
            source_date=spec.source_date,
            max_copies=config.max_copies_per_date,
        )
        return cached

    record = _download_and_record(
        spec,
        config=config,
        repository=resolved_repository,
        http_client=http_client,
    )
    _prune_old_copies(
        resolved_repository,
        source_name=spec.source_name,
        dataset_name=spec.dataset_name,
        source_date=spec.source_date,
        max_copies=config.max_copies_per_date,
    )
    return record


def _download_and_record(
    spec: RawFileSpec,
    *,
    config: RawFilesConfig,
    repository: RawFileRepository,
    http_client: Any,
) -> RawFileRecord:
    now = _utc_now()
    temp_path = config.raw_root / "_tmp" / f"{spec.file_name}.{uuid4().hex}.tmp"
    try:
        result = download_with_sha256(
            spec.source_url,
            temp_path,
            http_client=http_client,
        )
        if (
            spec.content_length is not None
            and result.downloaded_size != spec.content_length
        ):
            msg = (
                f"Raw file download size mismatch for {spec.source_url}: "
                f"expected {spec.content_length}, got {result.downloaded_size}"
            )
            raise RuntimeError(msg)

        final_path = _cache_path(config.raw_root, spec, result.sha256)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists() and local_file_matches(
            final_path,
            sha256=result.sha256,
            downloaded_size=result.downloaded_size,
        ):
            temp_path.unlink(missing_ok=True)
        else:
            temp_path.replace(final_path)

        record = RawFileRecord(
            id=None,
            source_name=spec.source_name,
            dataset_name=spec.dataset_name,
            source_date=spec.source_date,
            source_url=spec.source_url,
            local_path=str(final_path),
            sha256=result.sha256,
            content_length=spec.content_length,
            downloaded_size=result.downloaded_size,
            last_modified=spec.last_modified,
            etag=spec.etag,
            source_row_count=spec.source_row_count,
            first_seen_at=now,
            last_checked_at=now,
            downloaded_at=now,
            status="downloaded",
        )
        return repository.insert(record)
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        failed = RawFileRecord(
            id=None,
            source_name=spec.source_name,
            dataset_name=spec.dataset_name,
            source_date=spec.source_date,
            source_url=spec.source_url,
            local_path=None,
            sha256=None,
            content_length=spec.content_length,
            downloaded_size=None,
            last_modified=spec.last_modified,
            etag=spec.etag,
            source_row_count=spec.source_row_count,
            first_seen_at=now,
            last_checked_at=now,
            downloaded_at=None,
            status="failed",
            error_message=str(exc),
        )
        repository.insert(failed)
        raise


def _cache_path(raw_root: Path, spec: RawFileSpec, sha256: str) -> Path:
    return raw_root.joinpath(
        *spec.cache_relative_parts, f"sha256={sha256}", spec.file_name
    )


def _cached_record_matches(record: RawFileRecord, spec: RawFileSpec) -> bool:
    has_content_length = spec.content_length is not None
    has_last_modified = spec.last_modified is not None
    has_etag = spec.etag is not None
    has_source_row_count = spec.source_row_count is not None
    if (
        not has_content_length
        and not has_last_modified
        and not has_etag
        and not has_source_row_count
    ):
        return False
    if has_content_length and record.content_length != spec.content_length:
        return False
    if has_last_modified and record.last_modified != spec.last_modified:
        return False
    if has_etag and record.etag != spec.etag:
        return False
    if has_source_row_count and record.source_row_count != spec.source_row_count:
        return False
    return cached_record_is_valid(record)


def _prune_old_copies(
    repository: RawFileRepository,
    *,
    source_name: str,
    dataset_name: str,
    source_date: str,
    max_copies: int,
) -> None:
    if max_copies == 0:
        return

    records = repository.list_successes_for_source_date(
        source_name=source_name,
        dataset_name=dataset_name,
        source_date=source_date,
    )
    kept_paths: set[str] = set()
    pruned_paths: set[str] = set()
    for record in records:
        if record.local_path is None:
            continue
        if record.local_path in kept_paths or record.local_path in pruned_paths:
            continue
        if len(kept_paths) < max_copies:
            kept_paths.add(record.local_path)
        else:
            pruned_paths.add(record.local_path)

    for local_path in pruned_paths:
        path = Path(local_path)
        path.unlink(missing_ok=True)
        _remove_empty_parents(path.parent)

    repository.delete_successes_for_local_paths(pruned_paths)


def _remove_empty_parents(path: Path) -> None:
    for candidate in (path, path.parent):
        try:
            candidate.rmdir()
        except OSError:
            return


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
