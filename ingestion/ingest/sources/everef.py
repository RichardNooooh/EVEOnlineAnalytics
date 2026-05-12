"""Everef market history dlt source.

Everef publishes one compressed CSV per market date. This source first probes the
expected daily files, then streams available CSVs in pandas chunks into dlt.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import dlt
import pandas as pd
import pyarrow as pa
from dlt.sources.helpers import requests

from ingest.clients.everef import (
    BASE_URL,
    iter_market_history_url_items,
    parse_market_history_date,
    probe_market_history_file_item,
)
from ingest.contracts.market_history import (
    MARKET_HISTORY_ARROW_SCHEMA,
    MARKET_HISTORY_COLUMNS,
    MARKET_HISTORY_PRIMARY_KEY,
    validate_market_history_chunk,
)
from ingest.raw_files.config import (
    LOCAL_STORAGE_TARGET,
    resolve_raw_files_config,
)
from ingest.raw_files.everef import (
    list_cached_everef_market_history_files,
)

DEFAULT_CHUNKSIZE = 20_000
URL_INPUT_SOURCE = "url"
RAW_CACHE_INPUT_SOURCE = "raw-cache"
INPUT_SOURCES = (URL_INPUT_SOURCE, RAW_CACHE_INPUT_SOURCE)

logger = logging.getLogger(__name__)

_PROBE_CLIENT = requests.Client(
    raise_for_status=False,
    status_codes=(429, 500, 502, 503, 504),
)


@dlt.resource(name="market_history_urls", selected=False)
def list_market_history_urls(
    start_date: date,
    end_date: date,
    base_url: str = BASE_URL,
) -> Iterator[dict[str, str]]:
    """List expected Everef market history CSV URLs for an inclusive date range."""
    yield from iter_market_history_url_items(start_date, end_date, base_url)


@dlt.transformer(name="market_history_files", selected=False, parallelized=True)
def probe_market_history_file(item: dict[str, str]) -> Iterator[dict[str, Any]]:
    """Probe an Everef file URL and keep only readable files."""
    enriched_item = probe_market_history_file_item(
        item,
        http_client=_PROBE_CLIENT,
        logger=logger,
        request_exception_type=requests.RequestException,
        warn_missing=True,
        warn_zero_content_length=True,
        positive_content_length_only=False,
    )
    if enriched_item is None:
        return
    yield enriched_item


@dlt.resource(name="cached_market_history_files", selected=False)
def list_cached_market_history_files(
    start_date: date,
    end_date: date,
    base_url: str = BASE_URL,
    raw_root: str | None = None,
    raw_ledger_db: str | None = None,
    storage_target: str = LOCAL_STORAGE_TARGET,
    data_root: str | None = None,
) -> Iterator[dict[str, object]]:
    """List cached Everef market history files for a date range."""
    config = resolve_raw_files_config(
        raw_root=raw_root,
        db_path=raw_ledger_db,
        storage_target=storage_target,
        data_root=data_root,
    )
    yield from list_cached_everef_market_history_files(
        start_date,
        end_date,
        base_url=base_url,
        config=config,
    )


@dlt.transformer(
    name="market_history",
    parallelized=True,
    write_disposition={"disposition": "merge", "strategy": "delete-insert"},
    primary_key=MARKET_HISTORY_PRIMARY_KEY,
    merge_key="date",
    columns=MARKET_HISTORY_COLUMNS,
)
def read_market_history_csv(
    item: dict[str, Any],
    chunksize: int = DEFAULT_CHUNKSIZE,
) -> Iterator[pa.Table]:
    """Stream an Everef market history CSV into dlt as Arrow chunks."""
    if chunksize <= 0:
        msg = "chunksize must be greater than 0"
        raise ValueError(msg)

    source_url = item["url"]
    read_path = item.get("local_path", source_url)
    ingested_at = datetime.now(UTC).isoformat()

    try:
        chunks = pd.read_csv(read_path, compression="bz2", chunksize=chunksize)
    except (OSError, EOFError, UnicodeDecodeError, pd.errors.ParserError) as exc:
        msg = f"Could not read Everef CSV {source_url}: {exc}"
        raise RuntimeError(msg) from exc

    yielded_rows = 0
    chunk_index = 0
    seen_market_keys: set[tuple[Any, Any]] = set()
    while True:
        try:
            chunk = next(chunks)
        except StopIteration:
            break
        except (OSError, EOFError, UnicodeDecodeError, pd.errors.ParserError) as exc:
            msg = f"Could not read Everef CSV {source_url}: {exc}"
            raise RuntimeError(msg) from exc

        chunk_index += 1
        validate_market_history_chunk(
            chunk,
            file_url=source_url,
            market_date=item["market_date"],
            chunk_index=chunk_index,
        )

        market_keys = set(
            chunk[["region_id", "type_id"]].itertuples(index=False, name=None)
        )
        duplicate_market_keys = seen_market_keys.intersection(market_keys)
        if duplicate_market_keys:
            msg = (
                f"Everef CSV chunk {chunk_index} from {source_url} contains duplicate "
                f"(region_id, type_id) rows for source market_date {item['market_date']}"
            )
            raise ValueError(msg)
        seen_market_keys.update(market_keys)

        chunk["_source_market_date"] = item["market_date"]
        chunk["_source_url"] = source_url
        chunk["_source_local_path"] = item.get("local_path")
        chunk["_source_sha256"] = item.get("sha256")
        chunk["_source_content_length"] = item.get("content_length")
        chunk["_source_last_modified"] = item.get("last_modified")
        chunk["_source_downloaded_at"] = item.get("downloaded_at")
        chunk["_ingested_at"] = ingested_at

        yielded_rows += len(chunk)
        yield pa.Table.from_pandas(
            chunk,
            schema=MARKET_HISTORY_ARROW_SCHEMA,
            preserve_index=False,
        )
    if yielded_rows == 0:
        msg = f"Everef CSV contained no rows: {source_url}"
        raise ValueError(msg)


@dlt.source(name="everef")
def everef_market_history_source(
    start_date: str | date,
    end_date: str | date,
    base_url: str = BASE_URL,
    chunksize: int = DEFAULT_CHUNKSIZE,
    input_source: str = URL_INPUT_SOURCE,
    raw_root: str | None = None,
    raw_ledger_db: str | None = None,
    storage_target: str = LOCAL_STORAGE_TARGET,
    data_root: str | None = None,
):
    """Build the Everef market history dlt source for an inclusive date range."""
    parsed_start_date = parse_market_history_date(start_date)
    parsed_end_date = parse_market_history_date(end_date)

    if input_source == RAW_CACHE_INPUT_SOURCE:
        return list_cached_market_history_files(
            parsed_start_date,
            parsed_end_date,
            base_url,
            raw_root=raw_root,
            raw_ledger_db=raw_ledger_db,
            storage_target=storage_target,
            data_root=data_root,
        ) | read_market_history_csv(chunksize=chunksize)

    if input_source != URL_INPUT_SOURCE:
        msg = f"input_source must be one of {', '.join(INPUT_SOURCES)}"
        raise ValueError(msg)

    return (
        list_market_history_urls(parsed_start_date, parsed_end_date, base_url)
        | probe_market_history_file
        | read_market_history_csv(chunksize=chunksize)
    )
