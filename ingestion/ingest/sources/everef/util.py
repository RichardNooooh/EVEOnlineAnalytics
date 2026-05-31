from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import pyarrow as pa
import pyarrow.csv as pac

from ingest.cache import CacheObject, CacheResult
from ingest.publishers.ducklake import DuckLakeWriter, DuckLakeWriterMode, RawDuckLakeTable, compute_source_object_id
from ingest.sources.everef.client import EverefSnapshotClient
from ingest.sources.pipeline import PipelineProcessResult
from ingest.util import file_size, iter_dates

logger = logging.getLogger("ingest.sources.everef")

EVEREF_BASE = "https://data.everef.net"


def parse_last_modified_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            logger.warning("Could not parse last_modified timestamp value=%r", value)
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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
) -> list[CacheObject]:
    objects: list[CacheObject] = []
    date_count = 0
    with EverefSnapshotClient() as client:
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


def build_source_object_metadata(
    result: CacheResult,
    source_system: str,
    endpoint: str,
    source_market_date: date | None = None,
    snapshot_ts: datetime | None = None,
) -> dict:
    return {
        "source_object_id": compute_source_object_id(source_system, endpoint, result.version.source_url),
        "source_system": source_system,
        "endpoint": endpoint,
        "source_url": result.version.source_url,
        "storage_uri": result.path,
        "source_market_date": source_market_date,
        "snapshot_ts": snapshot_ts,
        "last_modified": parse_last_modified_timestamp(result.version.revalidation.last_modified),
        "content_length": result.version.revalidation.content_length,
        "sha256": result.version.sha256,
        "downloaded_at": result.version.fetched_at,
        "status": "downloaded",
    }


def parse_csv_to_arrow(
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
    return table


def publish_file_backed_rows(
    result: CacheResult,
    writer: DuckLakeWriter,
    *,
    source_system: str,
    endpoint: str,
    source_market_date: date,
    table_key: RawDuckLakeTable,
    mode: DuckLakeWriterMode,
    key_columns: list[str],
    parse_table: Callable[[CacheResult], pa.Table],
    snapshot_ts: datetime | None = None,
    log_context: dict[str, Any] | None = None,
) -> PipelineProcessResult:
    source_date_str = str(result.identity_key.get("source_date", "unknown"))
    soid = compute_source_object_id(source_system, endpoint, result.version.source_url)

    try:
        metadata = build_source_object_metadata(
            result,
            source_system,
            endpoint,
            source_market_date=source_market_date,
            snapshot_ts=snapshot_ts,
        )
        writer.upsert_source_object(metadata)

        table = parse_table(result)
        n = len(table)

        writer.upsert_source_object(
            {
                "source_object_id": soid,
                "status": "parsed",
                "parsed_at": datetime.now(UTC),
            }
        )

        table = table.append_column(
            "source_object_id",
            pa.array([soid] * n, type=pa.utf8()),
        )
        table = table.append_column(
            "source_market_date",
            pa.array([source_market_date] * n, type=pa.date32()),
        )
        if snapshot_ts is not None:
            table = table.append_column(
                "snapshot_ts",
                pa.array([snapshot_ts] * n, type=pa.timestamp("us", tz="UTC")),
            )

        metrics = writer.write(
            table,
            table=table_key,
            mode=mode,
            key_columns=key_columns,
        )

        writer.upsert_source_object(
            {
                "source_object_id": soid,
                "status": "ingested",
                "ingested_at": datetime.now(UTC),
                "row_count": n,
                "status_reason": None,
            }
        )

        extra_context = log_context or {}
        if snapshot_ts is None:
            logger.debug(
                "Processed source file source_date=%s table=%s attempted_rows=%d inserted_rows=%d matched_rows=%d",
                source_date_str,
                table_key.value,
                metrics.attempted_rows,
                metrics.inserted_rows,
                metrics.matched_rows,
            )
        else:
            logger.debug(
                "Processed source file source_date=%s snapshot_ts=%s %s table=%s attempted_rows=%d inserted_rows=%d matched_rows=%d",
                source_date_str,
                snapshot_ts,
                " ".join(f"{key}={value}" for key, value in extra_context.items()),
                table_key.value,
                metrics.attempted_rows,
                metrics.inserted_rows,
                metrics.matched_rows,
            )

        return PipelineProcessResult(
            success=True,
            source_date=source_date_str,
            write_metrics=(metrics,),
        )
    except Exception:
        logger.exception("Failed to process %s", result.identity_key)
        try:
            writer.upsert_source_object(
                {
                    "source_object_id": soid,
                    "status": "failed",
                    "status_reason": "see log for details",
                }
            )
        except Exception:
            pass
        return PipelineProcessResult(
            success=False,
            source_date=source_date_str,
        )
