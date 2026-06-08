from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Sequence
from datetime import date, datetime
from dataclasses import dataclass
from typing import Any

import pyarrow as pa
import pyarrow.csv as pac

from eve_ingest.raw_objects import CacheResult
from eve_ingest.ducklake.writer import DuckLakeSqlSnapshotSource, DuckLakeWriter
from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriterMode,
    RawDuckLakeTable,
    provenance_table_for_data_table,
)
from eve_ingest.sources.everef.provenance import build_source_object_metadata
from eve_ingest.workflows.raw_file_workflow import PipelineProcessResult
from eve_ingest.workflows.publication_errors import SnapshotScopePublishError
from eve_ingest.util import file_size

logger = logging.getLogger("eve_ingest.sources.everef")

_RETRYABLE_INSERT_MODES = {
    DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
    DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
}
_DUCKLAKE_CONFLICT_MAX_ATTEMPTS = 3
_DUCKLAKE_CONFLICT_BASE_DELAY_SECONDS = 0.2
_DUCKLAKE_CONFLICT_JITTER_SECONDS = 0.1


class ImmutableSnapshotSourceObjectChangedError(ValueError):
    pass


@dataclass(frozen=True)
class FileBackedPublicationContext:
    metadata: dict[str, Any]
    provenance_table: Any
    source_date_str: str
    source_object_id: str


def _elapsed_seconds(start_time: float) -> float:
    return time.perf_counter() - start_time


def _is_retryable_ducklake_conflict(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        ("ducklake_snapshot" in message and ("primary key" in message or "constraint" in message))
        or ("snapshot_id" in message and ("primary key" in message or "constraint" in message))
        or ("ducklake" in message and "conflicting changes" in message)
    )


def _check_append_snapshot_source_object(
    writer: DuckLakeWriter,
    *,
    soid: str,
    sha256: str,
    provenance_table,
    table_key: RawDuckLakeTable,
    source_date_str: str,
) -> bool:
    existing_sha256 = writer.source_object_ingested_sha256(soid, table=provenance_table)
    if existing_sha256 is None:
        return False
    if existing_sha256 == sha256:
        logger.info(
            "Skipping already ingested source object version source_date=%s table=%s source_object_id=%s sha256_prefix=%s",
            source_date_str,
            table_key.value,
            soid,
            sha256[:16],
        )
        return True
    raise ImmutableSnapshotSourceObjectChangedError(
        "Append snapshot source object changed after ingestion; snapshot URLs are expected immutable "
        f"source_date={source_date_str} table={table_key.value} source_object_id={soid} "
        f"existing_sha256_prefix={existing_sha256[:16]} new_sha256_prefix={sha256[:16]}"
    )


def _publish_transactional_rows_with_retry(
    writer: DuckLakeWriter,
    *,
    table: pa.Table,
    row_count: int,
    soid: str,
    sha256: str,
    provenance_table,
    table_key: RawDuckLakeTable,
    mode: DuckLakeWriterMode,
    key_columns: list[str],
    source_date_str: str,
):
    return _publish_snapshot_rows_with_retry(
        writer,
        soid=soid,
        sha256=sha256,
        provenance_table=provenance_table,
        table_key=table_key,
        mode=mode,
        source_date_str=source_date_str,
        publish_rows=lambda: writer.publish_source_object_rows(
            table,
            data_table=table_key,
            provenance_table=provenance_table,
            source_object_id=soid,
            mode=mode,
            row_count=row_count,
            key_columns=key_columns,
        ),
    )


def _publish_snapshot_rows_with_retry(
    writer: DuckLakeWriter,
    *,
    soid: str,
    sha256: str,
    provenance_table,
    table_key: RawDuckLakeTable,
    mode: DuckLakeWriterMode,
    source_date_str: str,
    publish_rows: Callable[[], Any],
):
    for attempt in range(1, _DUCKLAKE_CONFLICT_MAX_ATTEMPTS + 1):
        if mode is DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS and _check_append_snapshot_source_object(
            writer,
            soid=soid,
            sha256=sha256,
            provenance_table=provenance_table,
            table_key=table_key,
            source_date_str=source_date_str,
        ):
            return None
        try:
            return publish_rows()
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


def _build_file_backed_publication_context(
    result: CacheResult,
    *,
    source_system: str,
    endpoint: str,
    source_market_date: date,
    snapshot_ts: datetime | None,
    table_key: RawDuckLakeTable | None,
    provenance_table=None,
) -> FileBackedPublicationContext:
    source_date_str = str(result.identity_key.get("source_date", "unknown"))
    metadata = build_source_object_metadata(
        result,
        source_system,
        endpoint,
        source_market_date=source_market_date,
        snapshot_ts=snapshot_ts,
    )
    return FileBackedPublicationContext(
        metadata=metadata,
        provenance_table=provenance_table or provenance_table_for_data_table(table_key),
        source_date_str=source_date_str,
        source_object_id=metadata["source_object_id"],
    )


def _log_processed_source_file(
    *,
    source_date_str: str,
    snapshot_ts: datetime | None,
    log_context: dict[str, Any] | None,
    table_key: RawDuckLakeTable,
    metrics,
) -> None:
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
        return

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


def _log_file_backed_publication_success(
    *,
    context: FileBackedPublicationContext,
    write_metrics: tuple[Any, ...],
    elapsed_seconds: float,
    snapshot_ts: datetime | None,
    log_context: dict[str, Any] | None,
    table_key: RawDuckLakeTable,
) -> None:
    metrics = write_metrics[0]
    _log_processed_source_file(
        source_date_str=context.source_date_str,
        snapshot_ts=snapshot_ts,
        log_context=log_context,
        table_key=table_key,
        metrics=metrics,
    )
    logger.debug(
        "File-backed publication complete source_date=%s table=%s elapsed_seconds=%.3f",
        context.source_date_str,
        table_key.value,
        elapsed_seconds,
    )


def _normalize_write_metrics(metrics: Any) -> tuple[Any, ...]:
    if metrics is None:
        return ()
    if isinstance(metrics, Sequence):
        return tuple(metrics)
    return (metrics,)


def publish_file_backed_source_object(
    result: CacheResult,
    writer: DuckLakeWriter,
    *,
    source_system: str,
    endpoint: str,
    source_market_date: date,
    snapshot_ts: datetime | None,
    table_key: RawDuckLakeTable | None,
    provenance_table=None,
    skip_if_ingested: bool,
    publish_rows: Callable[[FileBackedPublicationContext], Any],
    raise_snapshot_scope_error: bool,
    log_success: Callable[[FileBackedPublicationContext, tuple[Any, ...], float], None] | None = None,
) -> PipelineProcessResult:
    context = _build_file_backed_publication_context(
        result,
        source_system=source_system,
        endpoint=endpoint,
        source_market_date=source_market_date,
        snapshot_ts=snapshot_ts,
        table_key=table_key,
        provenance_table=provenance_table,
    )

    started_at = time.monotonic()
    if (
        skip_if_ingested
        and table_key is not None
        and _check_append_snapshot_source_object(
            writer,
            soid=context.source_object_id,
            sha256=result.version.sha256,
            provenance_table=context.provenance_table,
            table_key=table_key,
            source_date_str=context.source_date_str,
        )
    ):
        return PipelineProcessResult(success=True, source_date=context.source_date_str)

    try:
        record_started_at = time.perf_counter()
        writer.record_source_object(context.metadata, table=context.provenance_table)
        logger.debug(
            "Recorded source object provenance source_date=%s table=%s duration_seconds=%.3f",
            context.source_date_str,
            "unknown" if table_key is None else table_key.value,
            _elapsed_seconds(record_started_at),
        )

        write_metrics = _normalize_write_metrics(publish_rows(context))
        if not write_metrics:
            logger.debug(
                "File-backed publication complete source_date=%s table=%s elapsed_seconds=%.3f result=skipped",
                context.source_date_str,
                "unknown" if table_key is None else table_key.value,
                time.monotonic() - started_at,
            )
            return PipelineProcessResult(success=True, source_date=context.source_date_str)

        if log_success is not None:
            log_success(context, write_metrics, time.monotonic() - started_at)
        return PipelineProcessResult(
            success=True,
            source_date=context.source_date_str,
            write_metrics=write_metrics,
        )
    except ImmutableSnapshotSourceObjectChangedError:
        raise
    except Exception as exc:
        logger.exception("Failed to process %s", result.identity_key)
        if raise_snapshot_scope_error:
            raise SnapshotScopePublishError(
                source_object_id=context.source_object_id,
                provenance_table=context.provenance_table,
                metadata=context.metadata,
                source_date=context.source_date_str,
            ) from exc
        try:
            writer.mark_source_object_failed(
                context.source_object_id,
                reason="see log for details",
                table=context.provenance_table,
            )
        except Exception:
            pass
        return PipelineProcessResult(
            success=False,
            source_date=context.source_date_str,
        )


def parse_csv_to_arrow(
    result: CacheResult,
    *,
    read_options: pac.ReadOptions | None = None,
    parse_options: pac.ParseOptions | None = None,
    convert_options: pac.ConvertOptions | None = None,
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
    parse_started_at = time.perf_counter()
    table = pac.read_csv(
        path,
        read_options=read_options,
        parse_options=parse_options,
        convert_options=convert_options,
    )
    n = len(table)
    logger.debug(
        "Parsed CSV to Arrow source_date=%s rows=%d columns=%d path=%s sha256_prefix=%s duration_seconds=%.3f",
        source_date,
        n,
        len(table.column_names),
        path,
        result.version.sha256[:16],
        _elapsed_seconds(parse_started_at),
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
    def publish_rows(context: FileBackedPublicationContext):
        parse_started_at = time.perf_counter()
        table = parse_table(result)
        n = len(table)
        logger.debug(
            "Prepared file-backed source table source_date=%s table=%s rows=%d duration_seconds=%.3f",
            context.source_date_str,
            table_key.value,
            n,
            _elapsed_seconds(parse_started_at),
        )

        enrich_started_at = time.perf_counter()
        table = table.append_column(
            "source_object_id",
            pa.array([context.source_object_id] * n, type=pa.utf8()),
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
        logger.debug(
            "Augmented file-backed source table source_date=%s table=%s rows=%d duration_seconds=%.3f",
            context.source_date_str,
            table_key.value,
            n,
            _elapsed_seconds(enrich_started_at),
        )

        publish_started_at = time.perf_counter()
        metrics = _publish_transactional_rows_with_retry(
            writer,
            table=table,
            row_count=n,
            soid=context.source_object_id,
            sha256=result.version.sha256,
            provenance_table=context.provenance_table,
            table_key=table_key,
            mode=mode,
            key_columns=key_columns,
            source_date_str=context.source_date_str,
        )
        logger.debug(
            "Published file-backed source table source_date=%s table=%s duration_seconds=%.3f",
            context.source_date_str,
            table_key.value,
            _elapsed_seconds(publish_started_at),
        )
        return metrics

    def log_success(
        context: FileBackedPublicationContext, write_metrics: tuple[Any, ...], elapsed_seconds: float
    ) -> None:
        _log_file_backed_publication_success(
            context=context,
            write_metrics=write_metrics,
            elapsed_seconds=elapsed_seconds,
            snapshot_ts=snapshot_ts,
            log_context=log_context,
            table_key=table_key,
        )

    return publish_file_backed_source_object(
        result,
        writer,
        source_system=source_system,
        endpoint=endpoint,
        source_market_date=source_market_date,
        snapshot_ts=snapshot_ts,
        table_key=table_key,
        skip_if_ingested=mode is DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
        publish_rows=publish_rows,
        raise_snapshot_scope_error=False,
        log_success=log_success,
    )


def publish_file_backed_snapshot_rows(
    result: CacheResult,
    writer: DuckLakeWriter,
    *,
    source_system: str,
    endpoint: str,
    source_market_date: date,
    snapshot_ts: datetime,
    table_key: RawDuckLakeTable,
    sql_source: DuckLakeSqlSnapshotSource,
    log_context: dict[str, Any] | None = None,
) -> PipelineProcessResult:
    def publish_rows(context: FileBackedPublicationContext):
        return _publish_snapshot_rows_with_retry(
            writer,
            soid=context.source_object_id,
            sha256=result.version.sha256,
            provenance_table=context.provenance_table,
            table_key=table_key,
            mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
            source_date_str=context.source_date_str,
            publish_rows=lambda: writer.publish_source_object_sql_rows(
                sql_source,
                data_table=table_key,
                provenance_table=context.provenance_table,
                source_object_id=context.source_object_id,
                mode=DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS,
                row_count=None,
            ),
        )

    def log_success(
        context: FileBackedPublicationContext, write_metrics: tuple[Any, ...], elapsed_seconds: float
    ) -> None:
        _log_file_backed_publication_success(
            context=context,
            write_metrics=write_metrics,
            elapsed_seconds=elapsed_seconds,
            snapshot_ts=snapshot_ts,
            log_context=log_context,
            table_key=table_key,
        )

    return publish_file_backed_source_object(
        result,
        writer,
        source_system=source_system,
        endpoint=endpoint,
        source_market_date=source_market_date,
        snapshot_ts=snapshot_ts,
        table_key=table_key,
        skip_if_ingested=True,
        publish_rows=publish_rows,
        raise_snapshot_scope_error=True,
        log_success=log_success,
    )
