from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from eve_ingest.cli.config import DuckLakeCliConfig, RawFilesCliConfig
from eve_ingest.ducklake.attach_config import build_ducklake_attach_config_from_url
from eve_ingest.ducklake.locks import (
    DuckLakeLockContext,
    hold_ducklake_lock_domains,
)
from eve_ingest.ducklake.provenance import SourceObjectProvenanceRepository
from eve_ingest.ducklake.raw_publish import RawTablePublisher
from eve_ingest.ducklake.session import DuckLakeSession
from eve_ingest.publication.context import PublishContext
from eve_ingest.publication.results import PublishResult
from eve_ingest.publication.specs import AppendSnapshotRows, DatasetPublisherSpec
from eve_ingest.raw_objects import CacheObject, CacheResult, UpdateMode
from eve_ingest.raw_objects.store import RawObjectStore
from eve_ingest.raw_objects.publication_registry import PublicationRegistry

logger = logging.getLogger(__name__)

##############################
# Types
##############################


class PipelineConfigProtocol:
    data_root: str
    raw_files: RawFilesCliConfig
    ducklake: DuckLakeCliConfig


@dataclass
class PipelineRunState:
    success: int = 0
    failed: int = 0
    successful_results: list[CacheResult] = field(default_factory=list)
    per_day_success: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    per_day_failed: dict[str, int] = field(default_factory=lambda: defaultdict(int))


##############################
# Pipeline Runner
##############################


def run_dataset_pipeline(
    *,
    config: PipelineConfigProtocol,
    spec: DatasetPublisherSpec,
    discover_objects: Callable[..., list[CacheObject]],
    publish_one: Callable[[CacheResult, PublishContext], PublishResult],
) -> int:
    objects = discover_objects(config)
    if not objects:
        logger.info("No source objects discovered dataset=%s", spec.dataset_name)
        return 0

    attach_config = build_ducklake_attach_config_from_url(
        config.ducklake.ducklake_catalog,
        data_path=f"{config.data_root}/datasets/ducklake/raw",
        metadata_schema=config.ducklake.ducklake_metadata_schema,
        postgres_pool_max_connections=config.ducklake.pg_pool_max_connections,
        postgres_pool_wait_timeout_millis=config.ducklake.pg_pool_wait_timeout_millis,
        postgres_pool_acquire_mode=config.ducklake.pg_pool_acquire_mode,
    )

    run_state = PipelineRunState()

    with RawObjectStore(
        dataset_name=spec.dataset_name,
        update_mode=spec.update_mode,
        raw_root=f"{config.data_root}/raw",
        ledger_url=config.raw_files.raw_ledger_url,
        raw_download_workers=config.raw_files.raw_download_workers,
    ) as store:
        publication_registry = PublicationRegistry(store.pubtrack)
        acquired = store.acquire_many(objects)
        results = publication_registry.filter_unpublished(acquired)
        if not results:
            logger.info("No unpublished raw objects dataset=%s", spec.dataset_name)
            return 0

        grouped = _group_by_publication_scope(spec, results)

        for publication_scope, scope_results in grouped.items():
            _process_publication_scope(
                config=config,
                spec=spec,
                publication_scope=publication_scope,
                scope_results=scope_results,
                store=store,
                publication_registry=publication_registry,
                attach_config=attach_config,
                publish_one=publish_one,
                run_state=run_state,
            )

    _log_pipeline_summary(spec=spec, run_state=run_state)
    return 1 if run_state.failed else 0


##############################
# Publication Scope Processing
##############################


def _process_publication_scope(
    *,
    config: PipelineConfigProtocol,
    spec: DatasetPublisherSpec,
    publication_scope: str,
    scope_results: list[CacheResult],
    store: RawObjectStore,
    publication_registry: PublicationRegistry,
    attach_config,
    publish_one: Callable[[CacheResult, PublishContext], PublishResult],
    run_state: PipelineRunState,
) -> None:
    source_date = _source_date_for_scope(publication_scope, scope_results)

    with hold_ducklake_lock_domains(
        catalog_url=config.ducklake.ducklake_catalog,
        lock_domains=_lock_domains_for_spec(spec),
        timeout_seconds=config.ducklake.lock_wait_timeout_seconds,
        context=DuckLakeLockContext(
            dataset=spec.dataset_name,
            publication_scope=publication_scope,
            table=spec.lock_context_table(),
            source_date=source_date,
            airflow_run_id=os.environ.get("AIRFLOW_CTX_RUN_ID") or None,
        ),
    ) as lock_token:
        scope_results = _filter_scope_results_after_lock(
            scope_results=scope_results,
            store=store,
            publication_registry=publication_registry,
            spec=spec,
            publication_scope=publication_scope,
        )
        if not scope_results:
            return

        with DuckLakeSession(attach_config, lock_token=lock_token) as session:
            raw_tables = RawTablePublisher(
                session=session,
                lock_token=lock_token,
                declared_policy=spec.writer_mode,
                dataset_name=spec.dataset_name,
            )
            provenance = SourceObjectProvenanceRepository(
                session=session,
                lock_token=lock_token,
            )
            ctx = PublishContext(
                spec=spec,
                session=session,
                raw_tables=raw_tables,
                provenance=provenance,
                publication_scope=publication_scope,
            )

            if isinstance(spec.write_policy, AppendSnapshotRows):
                successful = _publish_snapshot_scope_batch(
                    scope_results=scope_results,
                    ctx=ctx,
                    publish_one=publish_one,
                    run_state=run_state,
                )
            else:
                successful = _publish_per_object(
                    scope_results=scope_results,
                    ctx=ctx,
                    publish_one=publish_one,
                    run_state=run_state,
                )

        if successful:
            _mark_successful_results_published(
                publication_scope=publication_scope,
                successful_results=successful,
                publication_registry=publication_registry,
            )


##############################
# Post-Lock Filtering
##############################


def _filter_scope_results_after_lock(
    *,
    scope_results: list[CacheResult],
    store: RawObjectStore,
    publication_registry: PublicationRegistry,
    spec: DatasetPublisherSpec,
    publication_scope: str,
) -> list[CacheResult]:
    unpublished_results = publication_registry.filter_unpublished(scope_results)
    already_published_count = len(scope_results) - len(unpublished_results)

    current_results, stale_count, missing_stale_count = _filter_current_mutable_results(
        unpublished_results,
        store=store,
    )
    skipped_count = already_published_count + stale_count + missing_stale_count
    if skipped_count:
        logger.info(
            "Skipped raw objects after publication lock dataset=%s publication_scope=%s "
            "already_published=%d stale_versions=%d missing_stale_files=%d remaining=%d",
            spec.dataset_name,
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
    store: RawObjectStore,
) -> tuple[list[CacheResult], int, int]:
    mutable_results = [result for result in results if result.update_mode is UpdateMode.MUTABLE]
    if not mutable_results:
        return results, 0, 0

    current_states = store.load_current_states_for_results(mutable_results)
    current_results: list[CacheResult] = []
    stale_count = 0
    missing_stale_count = 0

    for result in results:
        if result.update_mode is not UpdateMode.MUTABLE:
            current_results.append(result)
            continue

        state = current_states.get(result.raw_object.ref.identity_hash)
        is_current = (
            state is not None
            and state.current_version.id == result.version.id
            and state.current_version.sha256 == result.version.sha256
            and state.current_version.local_path == result.version.local_path
        )
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


##############################
# Batch Publication
##############################


def _publish_snapshot_scope_batch(
    *,
    scope_results: list[CacheResult],
    ctx: PublishContext,
    publish_one: Callable[[CacheResult, PublishContext], PublishResult],
    run_state: PipelineRunState,
) -> list[CacheResult]:
    successful: list[CacheResult] = []

    try:
        with ctx.session.transaction():
            for raw_object in scope_results:
                result = publish_one(raw_object, ctx)
                if not result.success:
                    raise RuntimeError("Snapshot batch publish returned unsuccessful result")
                successful.append(raw_object)
                _record_success(run_state, raw_object, result)
    except Exception:
        logger.exception(
            "Failed snapshot publication scope dataset=%s publication_scope=%s",
            ctx.spec.dataset_name,
            ctx.publication_scope,
        )
        source_date = _source_date_for_scope(ctx.publication_scope, scope_results) or "unknown"
        run_state.failed += 1
        run_state.per_day_failed[source_date] += 1
        return []

    return successful


def _publish_per_object(
    *,
    scope_results: list[CacheResult],
    ctx: PublishContext,
    publish_one: Callable[[CacheResult, PublishContext], PublishResult],
    run_state: PipelineRunState,
) -> list[CacheResult]:
    successful: list[CacheResult] = []

    for raw_object in scope_results:
        try:
            result = publish_one(raw_object, ctx)
        except Exception:
            logger.exception("Failed source object identity_key=%s", raw_object.identity_key)
            source_date = str(raw_object.identity_key.get("source_date", "unknown"))
            run_state.failed += 1
            run_state.per_day_failed[source_date] += 1
            continue

        if result.success:
            successful.append(raw_object)
            _record_success(run_state, raw_object, result)
        else:
            source_date = result.source_date or str(raw_object.identity_key.get("source_date", "unknown"))
            run_state.failed += 1
            run_state.per_day_failed[source_date] += 1

    return successful


def _record_success(
    run_state: PipelineRunState,
    raw_object: CacheResult,
    result: PublishResult,
) -> None:
    source_date = result.source_date or str(raw_object.identity_key.get("source_date", "unknown"))
    run_state.success += 1
    run_state.successful_results.append(raw_object)
    run_state.per_day_success[source_date] += 1


def _mark_successful_results_published(
    *,
    publication_scope: str,
    successful_results: list[CacheResult],
    publication_registry: PublicationRegistry,
) -> None:
    publisher_run_id = os.environ.get("AIRFLOW_CTX_RUN_ID") or None
    publication_registry.mark_published_many(
        successful_results,
        publication_scope=publication_scope,
        publisher_run_id=publisher_run_id,
    )


##############################
# Helpers
##############################


def _group_by_publication_scope(
    spec: DatasetPublisherSpec,
    results: Iterable[CacheResult],
) -> dict[str, list[CacheResult]]:
    grouped: dict[str, list[CacheResult]] = defaultdict(list)
    for result in results:
        grouped[spec.scope_for(result.identity_key)].append(result)
    return {scope: grouped[scope] for scope in sorted(grouped)}


def _source_date_for_scope(
    publication_scope: str,
    results: list[CacheResult],
) -> str | None:
    if ":source_date=" in publication_scope:
        return publication_scope.rsplit("=", 1)[-1]
    if not results:
        return None
    source_date = results[0].identity_key.get("source_date")
    return source_date if isinstance(source_date, str) else None


def _lock_domains_for_spec(spec: DatasetPublisherSpec) -> tuple[str, ...]:
    return spec.lock_domains()


def _log_pipeline_summary(
    *,
    spec: DatasetPublisherSpec,
    run_state: PipelineRunState,
) -> None:
    logger.info(
        "Pipeline summary dataset=%s success=%d failed=%d marked_published=%d",
        spec.dataset_name,
        run_state.success,
        run_state.failed,
        len(run_state.successful_results),
    )
