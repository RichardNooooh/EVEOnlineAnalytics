from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from eve_ingest.raw_objects import Cache, CacheObject, CacheResult, GetMode, UpdateMode
from eve_ingest.cli.config import DuckLakeCliConfig, RawFilesCliConfig
from eve_ingest.ducklake.writer import DuckLakeWriter
from eve_ingest.ducklake.attach_config import build_ducklake_attach_config_from_url
from eve_ingest.ducklake.locks import (
    DuckLakeLockContext,
    DuckLakeLockTimeoutError,
    ducklake_lock_domains_for_publication_scope,
    hold_ducklake_lock_domains,
)
from eve_ingest.ducklake.raw_tables import DuckLakeWriteMetrics
from eve_ingest.raw_objects.ledger.models import PublicationContext

logger = logging.getLogger(__name__)

_PUBLICATION_SCOPE_DATASETS = {
    "market-orders": "market_orders",
    "fuzzwork-orders": "fuzzwork_orders",
    "market-history": "market_history",
    "reference-data": "references",
}

_LOCK_CONTEXT_TABLES = {
    "market-orders": "raw_market_orders",
    "fuzzwork-orders": "raw_fuzzwork_orders",
    "market-history": "raw_market_history",
}


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


def run_pipeline(
    *,
    dataset_name: str,
    update_mode: UpdateMode,
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

    logger.info(
        "Starting pipeline dataset=%s requested_objects=%d data_root=%s metadata_schema=%s",
        dataset_name,
        total_requested,
        config.data_root,
        config.ducklake.ducklake_metadata_schema,
    )

    with Cache(
        dataset_name=dataset_name,
        update_mode=update_mode,
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
            dataset_name=dataset_name,
            results=results,
        ).items():
            with (
                _hold_publication_domain_locks(
                    dataset_name=dataset_name,
                    catalog_url=config.ducklake.ducklake_catalog,
                    publication_scopes=(publication_scope,),
                    source_date=_publication_scope_source_date(publication_scope, scope_results),
                    timeout_seconds=config.ducklake.lock_wait_timeout_seconds,
                ),
                DuckLakeWriter(attach_config) as writer,
            ):
                scope_successful_results: list[CacheResult] = []
                for result in scope_results:
                    outcome = process_one(result, writer)
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
    dataset_name: str,
    catalog_url: str,
    publication_scopes: tuple[str, ...],
    source_date: str | None,
    timeout_seconds: float,
):
    # Publication scopes remain the semantic audit key. Lock domains are the physical
    # serialization key derived from those scopes.
    lock_domains: list[str] = []
    for publication_scope in publication_scopes:
        lock_domains.extend(ducklake_lock_domains_for_publication_scope(publication_scope))

    try:
        with hold_ducklake_lock_domains(
            catalog_url=catalog_url,
            lock_domains=lock_domains,
            timeout_seconds=timeout_seconds,
            context=DuckLakeLockContext(
                dataset=dataset_name,
                publication_scope=publication_scopes[0]
                if len(publication_scopes) == 1
                else ",".join(publication_scopes),
                table=_LOCK_CONTEXT_TABLES.get(dataset_name),
                source_date=source_date,
                airflow_run_id=os.environ.get("AIRFLOW_CTX_RUN_ID") or None,
            ),
        ):
            yield
    except DuckLakeLockTimeoutError as exc:
        raise PublicationScopeLockError(str(exc)) from exc


def _group_results_by_publication_scope(
    *,
    dataset_name: str,
    results: list[CacheResult],
) -> dict[str, list[CacheResult]]:
    grouped: dict[str, list[CacheResult]] = defaultdict(list)
    for result in results:
        grouped[_build_publication_scope(dataset_name=dataset_name, identity_key=result.identity_key)].append(result)
    return {publication_scope: grouped[publication_scope] for publication_scope in sorted(grouped)}


def _build_publication_scope(*, dataset_name: str, identity_key: dict[str, object]) -> str:
    if dataset_name == "reference-data":
        return "raw:references:full_extract"

    publication_dataset_name = _PUBLICATION_SCOPE_DATASETS.get(dataset_name)
    if publication_dataset_name is None:
        raise ValueError(f"Unsupported publication-scope dataset: {dataset_name}")

    source_date = identity_key.get("source_date")
    if not isinstance(source_date, str) or not source_date:
        raise ValueError(f"Missing source_date for publication scope dataset: {dataset_name}")

    return f"raw:{publication_dataset_name}:source_date={source_date}"


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
