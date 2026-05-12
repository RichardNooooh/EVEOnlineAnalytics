"""Everef raw market-history file acquisition."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

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
from ingest.raw_files.models import RawFileRecord
from ingest.raw_files.publisher import RawFileSpec, publish_raw_file
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
        item = _probe_market_history_file(
            market_date,
            base_url=base_url,
            http_client=http_client,
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
    return publish_raw_file(
        _market_history_raw_file_spec(item),
        config=config,
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


def _probe_market_history_file(
    market_date: date,
    *,
    base_url: str,
    http_client: Any,
) -> dict[str, Any] | None:
    return probe_market_history_file_item(
        market_history_url_item(market_date, base_url),
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
    )


def _cached_record_is_valid(record: RawFileRecord) -> bool:
    if record.local_path is None or record.sha256 is None:
        return False
    path = Path(record.local_path)
    if not path.exists() or not path.is_file():
        return False
    if (
        record.downloaded_size is not None
        and path.stat().st_size != record.downloaded_size
    ):
        return False
    from ingest.raw_files.downloader import sha256_file

    return sha256_file(path) == record.sha256
