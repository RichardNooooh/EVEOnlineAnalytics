from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from eve_ingest.raw_objects import Cache, CacheObject, CacheResult, GetMode, UpdateMode
from eve_ingest.cli.config import DuckLakeCliConfig, RawFilesCliConfig
from eve_ingest.ducklake.writer import DuckLakeWriter
from eve_ingest.ducklake.attach_config import build_ducklake_attach_config_from_url
from eve_ingest.ducklake.locks import (
    DuckLakeLockContext,
    DuckLakeLockTimeoutError,
    hold_ducklake_lock_domains,
)
from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriteMetrics,
    DuckLakeWriterMode,
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
)
from eve_ingest.raw_objects.ledger.models import CurrentRawObjectState
from eve_ingest.raw_objects.ledger.models import PublicationContext
from eve_ingest.workflows.publisher_specs import PublisherSpec

logger = logging.getLogger(__name__)


class PublicationScopeLockError(DuckLakeLockTimeoutError):
    """Raised when publication-scope single-writer lock acquisition times out."""


class _PipelineConfig(Protocol):
    """Minimum config surface needed by run_pipeline.

    Satisfied structurally by EverefCliConfig and EverefReferencesCliConfig.
    """

    data_root: str
    raw_files: RawFilesCliConfig
    ducklake: DuckLakeCliConfig


@dataclass(frozen=True)
class PipelineProcessResult:
    success: bool
    source_date: str | None
    write_metrics: tuple[DuckLakeWriteMetrics, ...] = ()


class _WriterModeEnforcingDuckLakeWriter:
    def __init__(
        self,
        writer: DuckLakeWriter,
        *,
        allowed_mode: DuckLakeWriterMode,
        dataset_name: str,
    ) -> None:
        self._writer = writer
        self._allowed_mode = allowed_mode
        self._dataset_name = dataset_name

    @property
    def write_history(self) -> tuple[DuckLakeWriteMetrics, ...]:
        return self._writer.write_history

    def write(
        self,
        arrow_table,
        *,
        table: RawDuckLakeTable,
        mode: DuckLakeWriterMode,
        key_columns: Sequence[str] = (),
    ) -> DuckLakeWriteMetrics:
        if mode != self._allowed_mode:
            requested_mode = getattr(mode, "value", str(mode))
            raise ValueError(
                "DuckLake writer mode does not match publisher declaration "
                f"dataset={self._dataset_name} table={table.value} "
                f"declared_mode={self._allowed_mode.value} requested_mode={requested_mode}"
            )
        return self._writer.write(arrow_table, table=table, mode=mode, key_columns=key_columns)

    def transaction(self):
        return self._writer.transaction()

    def upsert_source_object(self, data: dict, *, table: RawDuckLakeProvenanceTable) -> None:
        self._writer.upsert_source_object(data, table=table)


def run_pipeline(
    *,
    publisher_spec: PublisherSpec,
    objects: list[CacheObject],
    config: _PipelineConfig,
    process_one: Callable[[CacheResult, DuckLakeWriter], PipelineProcessResult],
) -> int:
    attach_config = build_ducklake_attach_config_from_url(
        config.ducklake.ducklake_catalog,
        data_path=f"{config.data_root}/datasets/ducklake/raw",
        metadata_schema=config.ducklake.ducklake_metadata_schema,
    )

    total_requested = len(objects)
    success = 0
    failed = 0
    per_day_requested = _count_by_source_date(objects)
    dataset_name = publisher_spec.dataset_name

    logger.info(
        "Starting pipeline dataset=%s requested_objects=%d data_root=%s metadata_schema=%s",
        dataset_name,
        total_requested,
        config.data_root,
        config.ducklake.ducklake_metadata_schema,
    )

    with Cache(
        dataset_name=dataset_name,
        update_mode=publisher_spec.update_mode,
        raw_root=f"{config.data_root}/raw",
        ledger_url=config.raw_files.raw_ledger_url,
    ) as cache:
        results = cache.get_many(objects, mode=GetMode.UNPUBLISHED)
        total_processable = len(results)
        per_day_processable = _count_by_source_date(results)

        if not results:
            logger.info("No unpublished raw objects to process dataset=%s", dataset_name)
            _log_pipeline_summary(
                dataset_name=dataset_name,
                requested_objects=total_requested,
                processable_objects=0,
                success=0,
                failed=0,
                marked_published=0,
                exit_code=0,
            )
            return 0

        successful_results: list[CacheResult] = []
        per_day_success: dict[str, int] = defaultdict(int)
        per_day_failed: dict[str, int] = defaultdict(int)
        per_day_metrics: dict[str, DuckLakeWriteMetrics] = {}
        for publication_scope, scope_results in _group_results_by_publication_scope(
            publisher_spec=publisher_spec,
            results=results,
        ).items():
            with _hold_publication_domain_locks(
                publisher_spec=publisher_spec,
                catalog_url=config.ducklake.ducklake_catalog,
                publication_scopes=(publication_scope,),
                source_date=_publication_scope_source_date(publication_scope, scope_results),
                timeout_seconds=config.ducklake.lock_wait_timeout_seconds,
            ) as lock_token:
                scope_results = _filter_scope_results_after_lock(
                    publisher_spec=publisher_spec,
                    publication_scope=publication_scope,
                    scope_results=scope_results,
                    cache=cache,
                )
                if not scope_results:
                    continue

                scope_successful_results: list[CacheResult] = []
                with DuckLakeWriter(attach_config, lock_token=lock_token) as writer:
                    constrained_writer = _WriterModeEnforcingDuckLakeWriter(
                        writer,
                        allowed_mode=publisher_spec.writer_mode,
                        dataset_name=dataset_name,
                    )
                    for result in scope_results:
                        outcome = process_one(result, constrained_writer)
                        source_date = outcome.source_date or str(result.identity_key.get("source_date", "unknown"))
                        if outcome.success:
                            success += 1
                            successful_results.append(result)
                            scope_successful_results.append(result)
                            per_day_success[source_date] += 1
                        else:
                            failed += 1
                            per_day_failed[source_date] += 1
                        for metric in outcome.write_metrics:
                            per_day_metrics[source_date] = _merge_metrics(per_day_metrics.get(source_date), metric)

                if scope_successful_results:
                    _mark_successful_results_published(
                        publication_scope=publication_scope,
                        successful_results=scope_successful_results,
                        cache=cache,
                    )

        if success and failed:
            logger.warning(
                "Partial publication dataset=%s success=%d failed=%d total=%d",
                dataset_name,
                success,
                failed,
                total_requested,
            )

    marked_published = len(successful_results)
    exit_code = 1 if failed else 0
    _log_pipeline_summary(
        dataset_name=dataset_name,
        requested_objects=total_requested,
        processable_objects=total_processable,
        success=success,
        failed=failed,
        marked_published=marked_published,
        exit_code=exit_code,
    )
    _log_pipeline_day_summaries(
        dataset_name=dataset_name,
        per_day_requested=per_day_requested,
        per_day_processable=per_day_processable,
        per_day_success=per_day_success,
        per_day_failed=per_day_failed,
        per_day_metrics=per_day_metrics,
    )

    return exit_code


@contextmanager
def _hold_publication_domain_locks(
    *,
    publisher_spec: PublisherSpec,
    catalog_url: str,
    publication_scopes: tuple[str, ...],
    source_date: str | None,
    timeout_seconds: float,
):
    lock_domains = publisher_spec.lock_domains()
    try:
        with hold_ducklake_lock_domains(
            catalog_url=catalog_url,
            lock_domains=lock_domains,
            timeout_seconds=timeout_seconds,
            context=DuckLakeLockContext(
                dataset=publisher_spec.dataset_name,
                publication_scope=publication_scopes[0]
                if len(publication_scopes) == 1
                else ",".join(publication_scopes),
                table=publisher_spec.lock_context_table(),
                source_date=source_date,
                airflow_run_id=os.environ.get("AIRFLOW_CTX_RUN_ID") or None,
            ),
        ) as lock_token:
            yield lock_token
    except DuckLakeLockTimeoutError as exc:
        raise PublicationScopeLockError(str(exc)) from exc


def _group_results_by_publication_scope(
    *,
    publisher_spec: PublisherSpec,
    results: list[CacheResult],
) -> dict[str, list[CacheResult]]:
    grouped: dict[str, list[CacheResult]] = defaultdict(list)
    for result in results:
        grouped[publisher_spec.publication_scope(result.identity_key)].append(result)
    return {publication_scope: grouped[publication_scope] for publication_scope in sorted(grouped)}


def _filter_scope_results_after_lock(
    *,
    publisher_spec: PublisherSpec,
    publication_scope: str,
    scope_results: list[CacheResult],
    cache: Cache,
) -> list[CacheResult]:
    published_versions = cache.pubtrack.filter_published(scope_results)
    unpublished_results = [
        result
        for result in scope_results
        if (result.raw_object.ref.identity_hash, result.version.sha256) not in published_versions
    ]
    already_published_count = len(scope_results) - len(unpublished_results)

    current_results, stale_count, missing_stale_count = _filter_current_mutable_results(
        unpublished_results,
        cache=cache,
    )
    skipped_count = already_published_count + stale_count + missing_stale_count
    if skipped_count:
        logger.info(
            "Skipped raw objects after publication lock dataset=%s publication_scope=%s "
            "already_published=%d stale_versions=%d missing_stale_files=%d remaining=%d",
            publisher_spec.dataset_name,
            publication_scope,
            already_published_count,
            stale_count,
            missing_stale_count,
            len(current_results),
        )
    return current_results


def _filter_current_mutable_results(
    results: list[CacheResult],
    *,
    cache: Cache,
) -> tuple[list[CacheResult], int, int]:
    mutable_results = [result for result in results if result.update_mode is UpdateMode.MUTABLE]
    if not mutable_results:
        return results, 0, 0

    current_states = cache.load_current_states_for_results(mutable_results)
    current_results: list[CacheResult] = []
    stale_count = 0
    missing_stale_count = 0

    for result in results:
        if result.update_mode is not UpdateMode.MUTABLE:
            current_results.append(result)
            continue

        state = current_states.get(result.raw_object.ref.identity_hash)
        is_current = _cache_result_matches_current_state(result, state)
        path_exists = Path(result.path).exists()
        if not is_current:
            if not path_exists:
                missing_stale_count += 1
            else:
                stale_count += 1
            continue
        if not path_exists:
            raise FileNotFoundError(f"Current cached raw object file is missing: {result.path}")
        current_results.append(result)

    return current_results, stale_count, missing_stale_count


def _cache_result_matches_current_state(
    result: CacheResult,
    state: CurrentRawObjectState | None,
) -> bool:
    if state is None:
        return False
    return (
        state.current_version.id == result.version.id
        and state.current_version.sha256 == result.version.sha256
        and state.current_version.local_path == result.version.local_path
    )


def _publication_scope_source_date(publication_scope: str, scope_results: list[CacheResult]) -> str | None:
    if ":source_date=" in publication_scope:
        return publication_scope.rsplit("=", 1)[-1]

    if not scope_results:
        return None

    source_date = scope_results[0].identity_key.get("source_date")
    return source_date if isinstance(source_date, str) and source_date else None


def _mark_successful_results_published(
    *, publication_scope: str, successful_results: list[CacheResult], cache: Cache
) -> None:
    publisher_run_id = os.environ.get("AIRFLOW_CTX_RUN_ID") or None
    cache.pubtrack.mark_published_many(
        successful_results,
        context=PublicationContext(
            publication_scope=publication_scope,
            publisher_run_id=publisher_run_id,
        ),
    )


def _count_by_source_date(objects: list[CacheObject] | list[CacheResult]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for obj in objects:
        source_date = str(obj.identity_key.get("source_date", "unknown"))
        counts[source_date] += 1
    return counts


def _merge_metrics(
    current: DuckLakeWriteMetrics | None,
    new: DuckLakeWriteMetrics,
) -> DuckLakeWriteMetrics:
    if current is None:
        return new
    return DuckLakeWriteMetrics(
        table=new.table,
        mode=new.mode,
        attempted_rows=current.attempted_rows + new.attempted_rows,
        inserted_rows=current.inserted_rows + new.inserted_rows,
        matched_rows=current.matched_rows + new.matched_rows,
        replaced_rows=current.replaced_rows + new.replaced_rows,
    )


def _log_pipeline_summary(
    *,
    dataset_name: str,
    requested_objects: int,
    processable_objects: int,
    success: int,
    failed: int,
    marked_published: int,
    exit_code: int,
) -> None:
    logger.info(
        "Pipeline summary dataset=%s requested_objects=%d processable_objects=%d success=%d failed=%d marked_published=%d exit_code=%d",
        dataset_name,
        requested_objects,
        processable_objects,
        success,
        failed,
        marked_published,
        exit_code,
    )


def _log_pipeline_day_summaries(
    *,
    dataset_name: str,
    per_day_requested: dict[str, int],
    per_day_processable: dict[str, int],
    per_day_success: dict[str, int],
    per_day_failed: dict[str, int],
    per_day_metrics: dict[str, DuckLakeWriteMetrics],
) -> None:
    for source_date in sorted(
        set(per_day_requested)
        | set(per_day_processable)
        | set(per_day_success)
        | set(per_day_failed)
        | set(per_day_metrics)
    ):
        metrics = per_day_metrics.get(source_date)
        logger.info(
            "Pipeline day summary dataset=%s source_date=%s requested_objects=%d processable_objects=%d success=%d failed=%d attempted_rows=%d inserted_rows=%d matched_rows=%d replaced_rows=%d",
            dataset_name,
            source_date,
            per_day_requested.get(source_date, 0),
            per_day_processable.get(source_date, 0),
            per_day_success.get(source_date, 0),
            per_day_failed.get(source_date, 0),
            0 if metrics is None else metrics.attempted_rows,
            0 if metrics is None else metrics.inserted_rows,
            0 if metrics is None else metrics.matched_rows,
            0 if metrics is None else metrics.replaced_rows,
        )
