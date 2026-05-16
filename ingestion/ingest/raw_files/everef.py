"""Everef raw market-history file acquisition."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from typing import Any

import requests

from ingest.clients.everef import (
    BASE_URL,
    fetch_market_history_totals,
    iter_dates,
    market_history_file_name,
    market_history_file_url,
    market_history_url_item,
    parse_market_history_date,
    probe_market_history_file_item,
)
from ingest.cli_config import RawFilesSyncCliConfig
from ingest.raw_files.config import (
    RawFilesConfig,
    resolve_raw_files_config,
)
from ingest.raw_files.models import RawFileRecord, cached_record_is_valid
from ingest.raw_files.publisher import RawFileSpec, publish_raw_file
from ingest.raw_files.repository import create_raw_file_repository

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
    check_headers: bool = False,
) -> list[RawFileRecord]:
    """Download missing or changed Everef market-history files into raw cache."""
    parsed_start = parse_market_history_date(start_date)
    parsed_end = parse_market_history_date(end_date)
    resolved_config = config or resolve_raw_files_config()
    records: list[RawFileRecord] = []
    totals = fetch_market_history_totals(
        base_url=base_url,
        http_client=http_client,
        logger=logger,
        request_exception_type=requests.RequestException,
    )
    repository = create_raw_file_repository(resolved_config.ledger_url)

    for market_date in iter_dates(parsed_start, parsed_end):
        item = market_history_url_item(market_date, base_url)
        if totals is not None:
            source_row_count = totals.get(market_date.isoformat())
            if source_row_count is None:
                logger.warning(
                    "Everef totals.json is missing market date %s: %s",
                    market_date.isoformat(),
                    item["url"],
                )
                continue
            item["source_row_count"] = source_row_count
        if check_headers:
            item = _probe_market_history_file_item(item, http_client=http_client)
        if item is None:
            continue
        cached = repository.find_latest_success(
            source_name=SOURCE_NAME,
            dataset_name=DATASET_NAME,
            source_date=market_date.isoformat(),
            source_url=item["url"],
        )
        records.append(
            acquire_everef_market_history_file(
                item,
                config=resolved_config,
                repository=repository,
                http_client=http_client,
            )
        )
        _warn_if_same_total_content_changed(cached, records[-1], item)

    return records


def sync_everef_market_history_files(
    config: RawFilesSyncCliConfig,
    *,
    http_client: Any = requests,
) -> list[RawFileRecord]:
    """Resolve raw config from CLI args, then sync Everef market-history files."""
    raw_config = resolve_raw_files_config(
        raw_root=config.raw_files.raw_root,
        ledger_url=config.raw_files.raw_ledger_url,
        max_copies_per_date=config.raw_files.raw_max_copies_per_date,
        storage_target=config.storage.storage_target,
        data_root=config.storage.data_root,
    )
    return acquire_everef_market_history_files(
        config.date_range.start_date,
        config.date_range.end_date,
        base_url=config.base_url or BASE_URL,
        config=raw_config,
        http_client=http_client,
        check_headers=config.check_headers,
    )


def acquire_everef_market_history_file(
    item: dict[str, Any],
    *,
    config: RawFilesConfig,
    repository=None,
    http_client: Any = requests,
) -> RawFileRecord:
    """Acquire one probed Everef market-history file into raw cache."""
    return publish_raw_file(
        _market_history_raw_file_spec(item),
        config=config,
        repository=repository,
        http_client=http_client,
    )


def list_cached_everef_market_history_files(
    start_date: str | date,
    end_date: str | date,
    *,
    base_url: str = BASE_URL,
    config: RawFilesConfig | None = None,
) -> Iterator[dict[str, object]]:
    """List cached Everef market-history source items for dlt."""
    parsed_start = parse_market_history_date(start_date)
    parsed_end = parse_market_history_date(end_date)
    resolved_config = config or resolve_raw_files_config()
    repository = create_raw_file_repository(resolved_config.ledger_url)

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
        if not cached_record_is_valid(cached):
            msg = (
                f"Everef raw file cache record is invalid for {market_date.isoformat()}"
            )
            raise FileNotFoundError(msg)
        yield _market_history_source_item(cached)


def _probe_market_history_file_item(
    item: dict[str, Any], *, http_client: Any
) -> dict[str, Any] | None:
    return probe_market_history_file_item(
        item,
        http_client=http_client,
        logger=logger,
        request_exception_type=requests.RequestException,
    )


def _market_history_raw_file_spec(item: dict[str, Any]) -> RawFileSpec:
    market_date = date.fromisoformat(item["market_date"])
    return RawFileSpec(
        source_name=SOURCE_NAME,
        dataset_name=DATASET_NAME,
        source_date=item["market_date"],
        source_url=item["url"],
        file_name=market_history_file_name(market_date),
        cache_relative_parts=(
            "everef",
            "market-history",
            f"year={market_date.year}",
            f"date={market_date.isoformat()}",
        ),
        content_length=item.get("content_length"),
        last_modified=item.get("last_modified"),
        etag=item.get("etag"),
        source_row_count=item.get("source_row_count"),
    )


def _warn_if_same_total_content_changed(
    cached: RawFileRecord | None,
    record: RawFileRecord,
    item: dict[str, Any],
) -> None:
    source_row_count = item.get("source_row_count")
    if (
        cached is None
        or source_row_count is None
        or cached.source_row_count != source_row_count
        or cached.sha256 is None
        or record.sha256 is None
        or cached.sha256 == record.sha256
    ):
        return
    logger.warning(
        "Everef market-history file changed with unchanged totals.json count for %s: %s",
        record.source_date,
        record.source_url,
    )


def _market_history_source_item(record: RawFileRecord) -> dict[str, object]:
    if record.local_path is None:
        msg = "raw file record has no local_path"
        raise ValueError(msg)

    return {
        "market_date": record.source_date,
        "url": record.source_url,
        "local_path": record.local_path,
        "sha256": record.sha256,
        "content_length": record.content_length,
        "last_modified": record.last_modified,
        "downloaded_at": record.downloaded_at,
    }
