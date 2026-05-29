from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, date, datetime

import pyarrow as pa
import pyarrow.csv as pac

from ingest.cache import CacheObject, CacheResult
from ingest.publishers.ducklake import DuckLakeWriter, RawDuckLakeTable
from ingest.sources.everef.client import EverefSnapshotClient
from ingest.util import file_size, iter_dates

logger = logging.getLogger("ingest.sources.everef")

EVEREF_BASE = "https://data.everef.net"

_DEFAULT_CLIENT = EverefSnapshotClient()


def list_snapshots(
    url_prefix: str,
    d: date,
    pattern: re.Pattern[str],
) -> list[str]:
    url = f"{EVEREF_BASE}/{url_prefix}/{d.year}/{d.isoformat()}/"
    logger.debug("Fetching snapshot listing source_date=%s url=%s", d.isoformat(), url)
    html = _DEFAULT_CLIENT.fetch_text(url)
    filenames = pattern.findall(html)
    if filenames:
        logger.info(
            "Discovered snapshots source_date=%s count=%d first=%s last=%s prefix=%s",
            d.isoformat(),
            len(filenames),
            filenames[0],
            filenames[-1],
            url_prefix,
        )
    else:
        logger.warning(
            "No snapshots discovered source_date=%s listing_url=%s prefix=%s",
            d.isoformat(),
            url,
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
) -> list[CacheObject]:
    def entries_fn(d: date) -> list[CacheObject]:
        filenames = list_snapshots(url_prefix, d, filename_pattern)
        return [
            CacheObject(
                source_url=f"{EVEREF_BASE}/{url_prefix}/{d.year}/{d.isoformat()}/{filename}",
                identity_key=identity_key_fn(filename, d),
            )
            for filename in filenames
        ]

    return collect_cache_objects(start_date, end_date, entries_fn)


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
        return [
            CacheObject(
                source_url=f"{EVEREF_BASE}/{url_prefix}/{d.year}/{filename}",
                identity_key=identity_key,
            )
        ]

    return collect_cache_objects(start_date, end_date, entries_fn)


def add_provenance(
    table: pa.Table,
    result: CacheResult,
    *,
    extra_columns: dict[str, pa.Array] | None = None,
) -> pa.Table:
    n = len(table)
    now = datetime.now(UTC)
    content_length = file_size(result.path)

    base_cols = [
        ("_source_url", pa.array([result.version.source_url] * n, type=pa.utf8())),
        ("_source_local_path", pa.array([result.path] * n, type=pa.utf8())),
        ("_source_sha256", pa.array([result.version.sha256] * n, type=pa.utf8())),
        ("_source_content_length", pa.array([content_length] * n, type=pa.int64())),
        ("_source_last_modified", pa.array([result.version.revalidation.last_modified] * n, type=pa.utf8())),
        ("_source_downloaded_at", pa.array([result.version.fetched_at] * n, type=pa.timestamp("us", tz="UTC"))),
        ("_ingested_at", pa.array([now] * n, type=pa.timestamp("us", tz="UTC"))),
    ]
    for name, col in base_cols:
        table = table.append_column(name, col)

    if extra_columns:
        for name, col in extra_columns.items():
            table = table.append_column(name, col)

    return table


def read_csv_to_arrow(
    result: CacheResult,
    *,
    read_options: pac.ReadOptions | None = None,
    parse_options: pac.ParseOptions | None = None,
) -> pa.Table:
    path = result.path
    source_date = str(result.identity_key["source_date"])
    content_length = file_size(path)
    expected = result.version.revalidation.content_length
    if expected is not None and content_length != expected:
        logger.warning(
            "File size mismatch for %s: on-disk %d, expected %d",
            source_date,
            content_length,
            expected,
        )
    table = pac.read_csv(path, read_options=read_options, parse_options=parse_options)
    n = len(table)
    logger.debug(
        "Parsed CSV to Arrow source_date=%s rows=%d columns=%d path=%s sha256_prefix=%s",
        source_date,
        n,
        len(table.column_names),
        path,
        result.version.sha256[:16],
    )
    if n == 0:
        logger.warning(
            "Zero-row CSV file source_date=%s path=%s source_url=%s",
            source_date,
            path,
            result.version.source_url,
        )
    return add_provenance(
        table,
        result,
        extra_columns={
            "_source_market_date": pa.array([source_date] * n, type=pa.utf8()),
        },
    )


def process_result(
    result: CacheResult,
    writer: DuckLakeWriter,
    *,
    table_key: RawDuckLakeTable,
    key_columns: list[str],
) -> bool:
    try:
        writer.write(read_csv_to_arrow(result), table=table_key, key_columns=key_columns)
        return True
    except Exception as e:
        logger.exception("Failed to process %s: %s", result.identity_key, e)
        return False
