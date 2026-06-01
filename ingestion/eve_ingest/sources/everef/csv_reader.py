from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pyarrow as pa
import pyarrow.csv as pac

from eve_ingest.raw_objects import CacheResult
from eve_ingest.ducklake.writer import DuckLakeWriter
from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriterMode,
    RawDuckLakeTable,
    compute_source_object_id,
    provenance_table_for_data_table,
)
from eve_ingest.sources.everef.provenance import build_source_object_metadata
from eve_ingest.workflows.raw_file_workflow import PipelineProcessResult
from eve_ingest.util import file_size

logger = logging.getLogger("eve_ingest.sources.everef")

_RETRYABLE_INSERT_MODES = {
    DuckLakeWriterMode.INSERT_MISSING_KEYS,
    DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
}
_DUCKLAKE_CONFLICT_MAX_ATTEMPTS = 3
_DUCKLAKE_CONFLICT_BASE_DELAY_SECONDS = 0.2
_DUCKLAKE_CONFLICT_JITTER_SECONDS = 0.1


def _is_retryable_ducklake_conflict(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        ("ducklake_snapshot" in message and ("primary key" in message or "constraint" in message))
        or ("snapshot_id" in message and ("primary key" in message or "constraint" in message))
        or ("ducklake" in message and "conflicting changes" in message)
    )


def _publish_transactional_rows_with_retry(
    writer: DuckLakeWriter,
    *,
    table: pa.Table,
    row_count: int,
    soid: str,
    provenance_table,
    table_key: RawDuckLakeTable,
    mode: DuckLakeWriterMode,
    key_columns: list[str],
    source_date_str: str,
):
    for attempt in range(1, _DUCKLAKE_CONFLICT_MAX_ATTEMPTS + 1):
        try:
            with writer.transaction():
                writer.upsert_source_object(
                    {
                        "source_object_id": soid,
                        "status": "parsed",
                        "parsed_at": datetime.now(UTC),
                    },
                    table=provenance_table,
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
                        "row_count": row_count,
                        "status_reason": None,
                    },
                    table=provenance_table,
                )
                return metrics
        except Exception as exc:
            should_retry = mode in _RETRYABLE_INSERT_MODES and _is_retryable_ducklake_conflict(exc)
            if not should_retry or attempt >= _DUCKLAKE_CONFLICT_MAX_ATTEMPTS:
                raise
            delay_seconds = (_DUCKLAKE_CONFLICT_BASE_DELAY_SECONDS * attempt) + random.uniform(
                0.0, _DUCKLAKE_CONFLICT_JITTER_SECONDS
            )
            logger.warning(
                "Retrying DuckLake insert-style publication after conflict source_date=%s table=%s mode=%s attempt=%d max_attempts=%d sleep_seconds=%.3f",
                source_date_str,
                table_key.value,
                mode.value,
                attempt + 1,
                _DUCKLAKE_CONFLICT_MAX_ATTEMPTS,
                delay_seconds,
            )
            time.sleep(delay_seconds)


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
    provenance_table = provenance_table_for_data_table(table_key)

    try:
        metadata = build_source_object_metadata(
            result,
            source_system,
            endpoint,
            source_market_date=source_market_date,
            snapshot_ts=snapshot_ts,
        )
        writer.upsert_source_object(metadata, table=provenance_table)

        table = parse_table(result)
        n = len(table)

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

        metrics = _publish_transactional_rows_with_retry(
            writer,
            table=table,
            row_count=n,
            soid=soid,
            provenance_table=provenance_table,
            table_key=table_key,
            mode=mode,
            key_columns=key_columns,
            source_date_str=source_date_str,
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
                },
                table=provenance_table,
            )
        except Exception:
            pass
        return PipelineProcessResult(
            success=False,
            source_date=source_date_str,
        )
