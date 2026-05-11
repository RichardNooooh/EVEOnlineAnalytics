"""Everef raw market-history file acquisition."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from ingest.clients.everef import (
    BASE_URL,
    iter_dates,
    market_history_file_name,
    market_history_file_url,
    market_history_url_item,
    parse_market_history_date,
    probe_market_history_file_item,
)
from ingest.raw_files.config import (
    RawFilesConfig,
    resolve_raw_files_config,
)
from ingest.raw_files.downloader import download_with_sha256, sha256_file
from ingest.raw_files.models import RawFileRecord
from ingest.raw_files.repository import RawFileRepository

SOURCE_NAME = "everef"
DATASET_NAME = "market_history"

logger = logging.getLogger(__name__)


def acquire_everef_market_history_files(
    start_date: str | date,
    end_date: str | date,
    *,
    base_url: str = BASE_URL,
    config: RawFilesConfig | None = None,
    http_client: Any = requests,
) -> list[RawFileRecord]:
    """Download missing or changed Everef market-history files into raw cache."""
    parsed_start = parse_market_history_date(start_date)
    parsed_end = parse_market_history_date(end_date)
    resolved_config = config or resolve_raw_files_config()
    records: list[RawFileRecord] = []

    for market_date in iter_dates(parsed_start, parsed_end):
        item = probe_market_history_file_item(
            market_history_url_item(market_date, base_url),
            http_client=http_client,
            logger=logger,
            request_exception_type=requests.RequestException,
        )
        if item is None:
            continue
        records.append(
            acquire_everef_market_history_file(
                item,
                config=resolved_config,
                http_client=http_client,
            )
        )

    return records


def acquire_everef_market_history_file(
    item: dict[str, Any],
    *,
    config: RawFilesConfig,
    http_client: Any = requests,
) -> RawFileRecord:
    """Acquire one probed Everef market-history file into raw cache."""
    repository = RawFileRepository(config.db_path)
    now = _utc_now()
    cached = repository.find_latest_success(
        source_name=SOURCE_NAME,
        dataset_name=DATASET_NAME,
        source_date=item["market_date"],
        source_url=item["url"],
    )
    if cached is not None and _cached_record_matches(cached, item):
        if cached.id is not None:
            repository.touch_checked(cached.id, now)
        logger.info("Everef raw file cache hit for %s", item["market_date"])
        _prune_old_copies(
            repository,
            source_date=item["market_date"],
            max_copies=config.max_copies_per_date,
        )
        return cached

    record = _download_and_record(
        item, config=config, repository=repository, http_client=http_client
    )
    _prune_old_copies(
        repository,
        source_date=item["market_date"],
        max_copies=config.max_copies_per_date,
    )
    return record


def list_cached_everef_market_history_files(
    start_date: str | date,
    end_date: str | date,
    *,
    base_url: str = BASE_URL,
    config: RawFilesConfig | None = None,
) -> Iterator[dict[str, object]]:
    """Yield cached Everef market-history source items for dlt."""
    parsed_start = parse_market_history_date(start_date)
    parsed_end = parse_market_history_date(end_date)
    resolved_config = config or resolve_raw_files_config()
    repository = RawFileRepository(resolved_config.db_path)

    for market_date in iter_dates(parsed_start, parsed_end):
        source_url = market_history_file_url(market_date, base_url)
        cached = repository.find_latest_success(
            source_name=SOURCE_NAME,
            dataset_name=DATASET_NAME,
            source_date=market_date.isoformat(),
            source_url=source_url,
        )
        if cached is None:
            msg = f"Everef raw file is not cached for {market_date.isoformat()}: {source_url}"
            raise FileNotFoundError(msg)
        if not _cached_record_is_valid(cached):
            msg = (
                f"Everef raw file cache record is invalid for {market_date.isoformat()}"
            )
            raise FileNotFoundError(msg)
        yield cached.to_source_item()


def _download_and_record(
    item: dict[str, Any],
    *,
    config: RawFilesConfig,
    repository: RawFileRepository,
    http_client: Any,
) -> RawFileRecord:
    now = _utc_now()
    market_date = date.fromisoformat(item["market_date"])
    temp_path = (
        config.raw_root
        / "_tmp"
        / f"{market_history_file_name(market_date)}.{uuid4().hex}.tmp"
    )
    try:
        result = download_with_sha256(item["url"], temp_path, http_client=http_client)
        expected_size = item.get("content_length")
        if expected_size is not None and result.downloaded_size != expected_size:
            msg = (
                f"Everef download size mismatch for {item['url']}: "
                f"expected {expected_size}, got {result.downloaded_size}"
            )
            raise RuntimeError(msg)

        final_path = _cache_path(config.raw_root, market_date, result.sha256)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists() and _local_file_matches(
            final_path,
            sha256=result.sha256,
            downloaded_size=result.downloaded_size,
        ):
            temp_path.unlink(missing_ok=True)
        else:
            temp_path.replace(final_path)

        record = RawFileRecord(
            id=None,
            source_name=SOURCE_NAME,
            dataset_name=DATASET_NAME,
            source_date=item["market_date"],
            source_url=item["url"],
            local_path=str(final_path),
            sha256=result.sha256,
            content_length=item.get("content_length"),
            downloaded_size=result.downloaded_size,
            last_modified=item.get("last_modified"),
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
            source_name=SOURCE_NAME,
            dataset_name=DATASET_NAME,
            source_date=item["market_date"],
            source_url=item["url"],
            local_path=None,
            sha256=None,
            content_length=item.get("content_length"),
            downloaded_size=None,
            last_modified=item.get("last_modified"),
            first_seen_at=now,
            last_checked_at=now,
            downloaded_at=None,
            status="failed",
            error_message=str(exc),
        )
        repository.insert(failed)
        raise


def _cache_path(raw_root: Path, market_date: date, sha256: str) -> Path:
    return (
        raw_root
        / "everef/market-history"
        / f"year={market_date.year}"
        / f"date={market_date.isoformat()}"
        / f"sha256={sha256}"
        / market_history_file_name(market_date)
    )


def _cached_record_matches(record: RawFileRecord, item: dict[str, Any]) -> bool:
    has_content_length = "content_length" in item
    has_last_modified = "last_modified" in item
    if not has_content_length and not has_last_modified:
        return False
    if has_content_length and record.content_length != item.get("content_length"):
        return False
    if has_last_modified and record.last_modified != item.get("last_modified"):
        return False
    return _cached_record_is_valid(record)


def _cached_record_is_valid(record: RawFileRecord) -> bool:
    if record.local_path is None or record.sha256 is None:
        return False
    path = Path(record.local_path)
    return _local_file_matches(
        path,
        sha256=record.sha256,
        downloaded_size=record.downloaded_size,
    )


def _local_file_matches(
    path: Path,
    *,
    sha256: str,
    downloaded_size: int | None,
) -> bool:
    if not path.exists() or not path.is_file():
        return False
    if downloaded_size is not None and path.stat().st_size != downloaded_size:
        return False
    return sha256_file(path) == sha256


def _prune_old_copies(
    repository: RawFileRepository,
    *,
    source_date: str,
    max_copies: int,
) -> None:
    if max_copies == 0:
        return

    records = repository.list_successes_for_source_date(
        source_name=SOURCE_NAME,
        dataset_name=DATASET_NAME,
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
