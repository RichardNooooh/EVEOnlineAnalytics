"""Everef market-history client helpers.

This module owns Everef URL construction, source-date iteration, and HTTP probe
metadata normalization so dlt sources and raw-file acquisition share one client
boundary.
"""

from __future__ import annotations

import logging
import json
from collections.abc import Iterator, Mapping, MutableMapping
from datetime import UTC, date, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

BASE_URL = "https://data.everef.net/market-history"


def parse_market_history_date(value: str | date) -> date:
    """Parse an ISO date or return an existing date instance."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def market_history_file_url(market_date: date, base_url: str = BASE_URL) -> str:
    """Build the Everef daily market history CSV URL."""
    return (
        f"{base_url.rstrip('/')}/{market_date.year}/"
        f"market-history-{market_date.isoformat()}.csv.bz2"
    )


def market_history_file_name(market_date: date) -> str:
    """Return the canonical Everef daily market history file name."""
    return f"market-history-{market_date.isoformat()}.csv.bz2"


def market_history_totals_url(base_url: str = BASE_URL) -> str:
    """Build Everef market-history totals.json URL."""
    return f"{base_url.rstrip('/')}/totals.json"


def iter_dates(start_date: date, end_date: date) -> Iterator[date]:
    """Yield inclusive dates between start_date and end_date."""
    if end_date < start_date:
        msg = "end_date must be on or after start_date"
        raise ValueError(msg)

    for offset in range((end_date - start_date).days + 1):
        yield start_date + timedelta(days=offset)


def iter_market_history_url_items(
    start_date: date,
    end_date: date,
    base_url: str = BASE_URL,
) -> Iterator[dict[str, str]]:
    """Yield expected Everef market-history URL items for a date range."""
    for market_date in iter_dates(start_date, end_date):
        yield market_history_url_item(market_date, base_url)


def market_history_url_item(
    market_date: date,
    base_url: str = BASE_URL,
) -> dict[str, str]:
    """Build one Everef market-history URL item."""
    return {
        "market_date": market_date.isoformat(),
        "url": market_history_file_url(market_date, base_url),
    }


def probe_market_history_file_item(
    item: Mapping[str, str],
    *,
    http_client: Any,
    logger: logging.Logger,
    request_exception_type: type[Exception] | tuple[type[Exception], ...] = Exception,
    warn_missing: bool = False,
    warn_zero_content_length: bool = False,
    positive_content_length_only: bool = True,
) -> dict[str, Any] | None:
    """Probe one Everef market-history URL item and return metadata if readable."""
    try:
        response = http_client.head(item["url"], allow_redirects=True)
    except request_exception_type as exc:
        msg = f"Everef probe failed at {item['url']}: {exc}"
        raise RuntimeError(msg) from exc

    if response.status_code == 404:
        logger.warning(
            "Everef file missing for %s: %s", item["market_date"], item["url"]
        )
        return None

    if response.status_code >= 400:
        msg = f"Unexpected Everef status HTTP {response.status_code} for {item['url']}"
        raise RuntimeError(msg)

    enriched_item: dict[str, Any] = dict(item)
    update_market_history_file_metadata(
        enriched_item,
        response.headers,
        logger=logger,
        warn_missing=warn_missing,
        warn_zero_content_length=warn_zero_content_length,
        positive_content_length_only=positive_content_length_only,
    )
    return enriched_item


def fetch_market_history_totals(
    *,
    base_url: str = BASE_URL,
    http_client: Any,
    logger: logging.Logger,
    request_exception_type: type[Exception] | tuple[type[Exception], ...] = Exception,
) -> dict[str, int]:
    """Fetch Everef totals.json as market_date -> row count."""
    totals_url = market_history_totals_url(base_url)
    try:
        response = http_client.get(totals_url, stream=False)
    except request_exception_type as exc:
        msg = f"Everef totals fetch failed at {totals_url}: {exc}"
        raise RuntimeError(msg) from exc

    if response.status_code >= 400:
        msg = f"Unexpected Everef status HTTP {response.status_code} for {totals_url}"
        raise RuntimeError(msg)

    try:
        payload = json.loads(response.content)
    except json.JSONDecodeError as exc:
        msg = f"Everef totals.json is not valid JSON at {totals_url}: {exc}"
        raise RuntimeError(msg) from exc

    if not isinstance(payload, dict):
        msg = f"Everef totals.json must be a JSON object at {totals_url}"
        raise RuntimeError(msg)

    totals: dict[str, int] = {}
    for market_date, value in payload.items():
        if not isinstance(market_date, str):
            logger.warning("Everef totals.json has non-string key: %r", market_date)
            continue
        if not isinstance(value, int):
            logger.warning(
                "Everef totals.json has non-integer count for %s: %r",
                market_date,
                value,
            )
            continue
        totals[market_date] = value
    return totals


def update_market_history_file_metadata(
    item: MutableMapping[str, Any],
    headers: Mapping[str, str],
    *,
    logger: logging.Logger,
    warn_missing: bool = False,
    warn_zero_content_length: bool = False,
    positive_content_length_only: bool = True,
) -> None:
    """Enrich an Everef market-history source item from HTTP validators."""
    content_length = headers.get("content-length")
    if content_length is None:
        if warn_missing:
            logger.warning(
                "Everef is missing content-length header for %s", item["url"]
            )
    else:
        _update_content_length(
            item,
            content_length,
            logger=logger,
            warn_zero=warn_zero_content_length,
            positive_only=positive_content_length_only,
        )

    last_modified = headers.get("last-modified")
    if last_modified is None:
        if warn_missing:
            logger.warning("Everef is missing last-modified header for %s", item["url"])
    else:
        _update_last_modified(item, last_modified, logger=logger)

    etag = headers.get("etag")
    if etag is not None:
        item["etag"] = etag


def _update_content_length(
    item: MutableMapping[str, Any],
    content_length: str,
    *,
    logger: logging.Logger,
    warn_zero: bool,
    positive_only: bool,
) -> None:
    try:
        parsed_length = int(content_length)
    except ValueError:
        logger.warning(
            "Everef returned invalid content-length=%r for %s",
            content_length,
            item["url"],
        )
        return

    if parsed_length == 0:
        if warn_zero:
            logger.warning("Everef file has content-length of 0: %s", item["url"])
        return

    if positive_only and parsed_length <= 0:
        return

    item["content_length"] = parsed_length


def _update_last_modified(
    item: MutableMapping[str, Any],
    last_modified: str,
    *,
    logger: logging.Logger,
) -> None:
    try:
        last_modified_dt = parsedate_to_datetime(last_modified)
    except ValueError:
        logger.warning(
            "Everef returned invalid last-modified=%r for %s",
            last_modified,
            item["url"],
        )
        return

    item["last_modified"] = last_modified_dt.astimezone(UTC).isoformat()
