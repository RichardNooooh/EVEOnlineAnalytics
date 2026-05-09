"""Everef market history dlt source.

Everef publishes one compressed CSV per market date. This source first probes the
expected daily files, then streams available CSVs in pandas chunks into dlt.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
import logging
from typing import Any

import dlt
from dlt.sources.helpers import requests
import pandas as pd

from eve_market_ingestion.contracts.market_history import MARKET_HISTORY_COLUMNS
from eve_market_ingestion.contracts.market_history import MARKET_HISTORY_PRIMARY_KEY
from eve_market_ingestion.contracts.market_history import validate_market_history_chunk

BASE_URL = "https://data.everef.net/market-history"
DEFAULT_CHUNKSIZE = 20_000

logger = logging.getLogger(__name__)

_PROBE_CLIENT = requests.Client(
    raise_for_status=False,
    status_codes=(429, 500, 502, 503, 504),
)


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


def iter_dates(start_date: date, end_date: date) -> Iterator[date]:
    """Yield inclusive dates between start_date and end_date."""
    if end_date < start_date:
        msg = "end_date must be on or after start_date"
        raise ValueError(msg)

    for offset in range((end_date - start_date).days + 1):
        yield start_date + timedelta(days=offset)


def _update_content_length(item: dict[str, Any], response: requests.Response) -> None:
    content_length = response.headers.get("content-length")
    if content_length is None:
        logger.warning("Everef is missing content-length header for %s", item["url"])
        return

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
        logger.warning("Everef file has content-length of 0: %s", item["url"])
        return

    item["content_length"] = parsed_length


def _update_last_modified(item: dict[str, Any], response: requests.Response) -> None:
    last_modified = response.headers.get("last-modified")
    if last_modified is None:
        logger.warning("Everef is missing last-modified header for %s", item["url"])
        return

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


@dlt.resource(name="market_history_urls", selected=False)
def list_market_history_urls(
    start_date: date,
    end_date: date,
    base_url: str = BASE_URL,
) -> Iterator[dict[str, str]]:
    """List expected Everef market history CSV URLs for an inclusive date range."""
    for market_date in iter_dates(start_date, end_date):
        yield {
            "market_date": market_date.isoformat(),
            "url": market_history_file_url(market_date, base_url),
        }


@dlt.transformer(name="market_history_files", selected=False, parallelized=True)
def probe_market_history_file(item: dict[str, str]) -> Iterator[dict[str, Any]]:
    """Probe an Everef file URL and keep only readable files."""
    yield from _probe_market_history_file(item)


def _probe_market_history_file(item: dict[str, str]) -> Iterator[dict[str, Any]]:
    """Probe one Everef file URL without dlt parallel wrapper."""
    try:
        response = _PROBE_CLIENT.head(item["url"], allow_redirects=True)
    except requests.RequestException as exc:
        msg = f"Everef probe failed at {item['url']}: {exc}"
        raise RuntimeError(msg) from exc

    if response.status_code == 404:
        logger.warning(
            "Everef file missing for %s: %s",
            item["market_date"],
            item["url"],
        )
        return

    if response.status_code >= 400:
        msg = f"Unexpected Everef status HTTP {response.status_code} for {item['url']}"
        raise RuntimeError(msg)

    enriched_item: dict[str, Any] = dict(item)
    _update_content_length(enriched_item, response)
    _update_last_modified(enriched_item, response)

    yield enriched_item


@dlt.transformer(
    name="market_history",
    parallelized=True,
    write_disposition="replace",
    primary_key=MARKET_HISTORY_PRIMARY_KEY,
    columns=MARKET_HISTORY_COLUMNS,
)
def read_market_history_csv(
    item: dict[str, Any],
    chunksize: int = DEFAULT_CHUNKSIZE,
) -> Iterator[pd.DataFrame]:
    """Stream an Everef market history CSV into dlt as pandas chunks."""
    yield from _read_market_history_csv(item, chunksize=chunksize)


def _read_market_history_csv(
    item: dict[str, Any],
    chunksize: int = DEFAULT_CHUNKSIZE,
) -> Iterator[pd.DataFrame]:
    """Stream one Everef market history CSV without dlt parallel wrapper."""
    if chunksize <= 0:
        msg = "chunksize must be greater than 0"
        raise ValueError(msg)

    file_url = item["url"]
    ingested_at = datetime.now(UTC).isoformat()

    try:
        chunks = pd.read_csv(file_url, compression="bz2", chunksize=chunksize)
        yielded_rows = 0
        for chunk_index, chunk in enumerate(chunks, start=1):
            validate_market_history_chunk(
                chunk,
                file_url=file_url,
                market_date=item["market_date"],
                chunk_index=chunk_index,
            )

            chunk["_source_market_date"] = item["market_date"]
            chunk["_source_url"] = file_url
            chunk["_source_content_length"] = item.get("content_length")
            chunk["_source_last_modified"] = item.get("last_modified")
            chunk["_ingested_at"] = ingested_at

            yielded_rows += len(chunk)
            yield chunk
        if yielded_rows == 0:
            msg = f"Everef CSV contained no rows: {file_url}"
            raise ValueError(msg)
    except Exception as exc:
        msg = f"Could not read Everef CSV {file_url}: {exc}"
        raise RuntimeError(msg) from exc


@dlt.source(name="everef")
def everef_market_history_source(
    start_date: str | date,
    end_date: str | date,
    base_url: str = BASE_URL,
    chunksize: int = DEFAULT_CHUNKSIZE,
):
    """Build the Everef market history dlt source for an inclusive date range."""
    parsed_start_date = parse_market_history_date(start_date)
    parsed_end_date = parse_market_history_date(end_date)

    return (
        list_market_history_urls(parsed_start_date, parsed_end_date, base_url)
        | probe_market_history_file
        | read_market_history_csv(chunksize=chunksize)
    )
