from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date

from eve_ingest.raw_objects import CacheObject
from eve_ingest.sources.everef.listing_client import EverefSnapshotClient
from eve_ingest.util import iter_dates

logger = logging.getLogger("eve_ingest.sources.everef")

EVEREF_BASE = "https://data.everef.net"


def list_snapshots(
    url_prefix: str,
    d: date,
    pattern: re.Pattern[str],
    client: EverefSnapshotClient,
) -> list[str]:
    url = f"{EVEREF_BASE}/{url_prefix}/{d.year}/{d.isoformat()}/"
    logger.debug("Fetching snapshot listing source_date=%s url=%s", d.isoformat(), url)
    html = client.fetch_text(url)
    filenames = pattern.findall(html)
    if not filenames:
        logger.warning(
            "No snapshots discovered source_date=%s listing_url=%s prefix=%s",
            d.isoformat(),
            url,
            url_prefix,
        )
    first = filenames[0] if filenames else "-"
    last = filenames[-1] if filenames else "-"
    logger.info(
        "Snapshot listing source_date=%s snapshot_count=%d first=%s last=%s prefix=%s",
        d.isoformat(),
        len(filenames),
        first,
        last,
        url_prefix,
    )
    return filenames


def collect_cache_objects(
    start_date: date,
    end_date: date,
    entries_fn: Callable[[date], list[CacheObject]],
) -> list[CacheObject]:
    objects: list[CacheObject] = []
    date_count = 0
    for d in iter_dates(start_date, end_date):
        date_count += 1
        objects.extend(entries_fn(d))
    logger.info(
        "Collect cache objects date_count=%d total_snapshots=%d",
        date_count,
        len(objects),
    )
    return objects


def build_listed_objects(
    start_date: date,
    end_date: date,
    *,
    url_prefix: str,
    filename_pattern: re.Pattern[str],
    identity_key_fn: Callable[[str, date], dict[str, str]],
    client: EverefSnapshotClient | None = None,
) -> list[CacheObject]:
    if client is None:
        with EverefSnapshotClient() as owned_client:
            return _build_listed_objects(
                start_date,
                end_date,
                url_prefix=url_prefix,
                filename_pattern=filename_pattern,
                identity_key_fn=identity_key_fn,
                client=owned_client,
            )
    return _build_listed_objects(
        start_date,
        end_date,
        url_prefix=url_prefix,
        filename_pattern=filename_pattern,
        identity_key_fn=identity_key_fn,
        client=client,
    )


def _build_listed_objects(
    start_date: date,
    end_date: date,
    *,
    url_prefix: str,
    filename_pattern: re.Pattern[str],
    identity_key_fn: Callable[[str, date], dict[str, str]],
    client: EverefSnapshotClient,
) -> list[CacheObject]:
    objects: list[CacheObject] = []
    date_count = 0
    for d in iter_dates(start_date, end_date):
        date_count += 1
        filenames = list_snapshots(url_prefix, d, filename_pattern, client=client)
        objects.extend(
            CacheObject(
                source_url=f"{EVEREF_BASE}/{url_prefix}/{d.year}/{d.isoformat()}/{filename}",
                identity_key=identity_key_fn(filename, d),
            )
            for filename in filenames
        )
    logger.info(
        "Collect cache objects date_count=%d total_snapshots=%d",
        date_count,
        len(objects),
    )
    return objects


def build_deterministic_objects(
    start_date: date,
    end_date: date,
    *,
    url_prefix: str,
    filename_prefix: str = "",
    suffix: str = ".csv.bz2",
    identity_key_fn: Callable[[date], dict[str, str]] | None = None,
) -> list[CacheObject]:
    def entries_fn(d: date) -> list[CacheObject]:
        filename = f"{filename_prefix}{d.isoformat()}{suffix}"
        identity_key = {"source_date": d.isoformat()} if identity_key_fn is None else identity_key_fn(d)
        logger.info(
            "Queued daily archive source_date=%s filename=%s prefix=%s",
            d.isoformat(),
            filename,
            url_prefix,
        )
        return [
            CacheObject(
                source_url=f"{EVEREF_BASE}/{url_prefix}/{d.year}/{filename}",
                identity_key=identity_key,
            )
        ]

    return collect_cache_objects(start_date, end_date, entries_fn)
