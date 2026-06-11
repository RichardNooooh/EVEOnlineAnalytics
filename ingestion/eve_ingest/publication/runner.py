from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

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
from eve_ingest.publication.source_prep import SourcePreparationContext
from eve_ingest.publication.service import PublicationService
from eve_ingest.publication.results import PublishResult
from eve_ingest.publication.specs import AppendSnapshotRows, DatasetPublisherSpec
from eve_ingest.raw_objects import RawObjectRequest, AcquiredRawObject
from eve_ingest.raw_objects.ledger.models import PublicationContext
from eve_ingest.raw_objects.publishing import PublicationTracker
from eve_ingest.raw_objects.store import RawObjectStore

logger = logging.getLogger(__name__)

##############################
# Types
##############################


class PipelineConfigProtocol(Protocol):
    data_root: str
    raw_files: RawFilesCliConfig
    ducklake: DuckLakeCliConfig


@dataclass(frozen=True)
class PipelineRuntimeContext:
    publisher_run_id: str | None = None


@dataclass
class PipelineRunState:
    success: int = 0
    failed: int = 0
    successful_results: list[AcquiredRawObject] = field(default_factory=list)
    per_day_success: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    per_day_failed: dict[str, int] = field(default_factory=lambda: defaultdict(int))


##############################
# Pipeline Runner
##############################


def run_dataset_pipeline(
    *,
    config: PipelineConfigProtocol,
    spec: DatasetPublisherSpec,
    discover_objects: Callable[..., list[RawObjectRequest]],
    publish_one: Callable[[AcquiredRawObject, PublishContext], PublishResult],
    runtime_context: PipelineRuntimeContext | None = None,
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
        acquired = store.acquire_many(objects)
        results = store.pubtrack.filter_unpublished(acquired)
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
                pubtrack=store.pubtrack,
                attach_config=attach_config,
                publish_one=publish_one,
                run_state=run_state,
                runtime_context=runtime_context,
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
    scope_results: list[AcquiredRawObject],
    store: RawObjectStore,
    pubtrack: PublicationTracker,
    attach_config,
    publish_one: Callable[[AcquiredRawObject, PublishContext], PublishResult],
    run_state: PipelineRunState,
    runtime_context: PipelineRuntimeContext | None = None,
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
            airflow_run_id=runtime_context.publisher_run_id if runtime_context else None,
        ),
    ) as lock_token:
        scope_results = _filter_scope_results_after_lock(
            scope_results=scope_results,
            store=store,
            pubtrack=pubtrack,
            spec=spec,
            publication_scope=publication_scope,
        )
        if not scope_results:
            return

        #
        # The DuckLake session below commits data and provenance to DuckLake
        # within a single DuckDB transaction. When the session context manager
        # exits, the DuckLake data is durable.
        #
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
            prep_ctx = SourcePreparationContext(session=session)
            service = PublicationService(
                raw_tables=raw_tables,
                provenance=provenance,
                session=session,
                spec=spec,
            )
            ctx = PublishContext(
                spec=spec,
                prep_ctx=prep_ctx,
                service=service,
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

        # ------------------------------------------------------------------
        # M5 eventual-consistency boundary: DuckLake commit vs.
        # PostgreSQL publication marker.
        #
        # DuckLake session exited above — data and provenance are durable in
        # DuckLake. The PostgreSQL raw-object ledger publication markers are
        # written below, still under the DuckLake advisory lock but NOT in
        # the same transaction as the DuckLake commit.
        #
        # Crash window:
        #   1. DuckLake commit succeeds (session exit).
        #   2. Process crashes before or during the PostgreSQL marker write.
        #   3. On retry, the raw-object appears unpublished in PostgreSQL.
        #   4. The pipeline reprocesses it.
        #
        # Why this is acceptable: Append-snapshot publication checks DuckLake
        # provenance (SHA256) before inserting rows. If the SHA already
        # exists from the previous (durable) attempt, the insert is skipped.
        # This idempotency prevents data duplication across the boundary.
        #
        # A dedicated reconciler could scan DuckLake provenance to back-fill
        # missing PostgreSQL publication markers without reprocessing —
        # see the M1 reconciler design.
        #
        # TODO: Implement reconciler to back-fill PostgreSQL publication markers from DuckLake provenance
        #
        # If a retry path needs to be fully source-idempotent without
        # touching the raw-object ledger, consider filtering by DuckLake
        # provenance in addition to the PostgreSQL publication marker check.
        # ------------------------------------------------------------------

        if successful:
            logger.info(
                "Marking raw-object versions published dataset=%s publication_scope=%s count=%d",
                spec.dataset_name,
                publication_scope,
                len(successful),
            )
            _mark_successful_results_published(
                publication_scope=publication_scope,
                successful_results=successful,
                pubtrack=pubtrack,
                publisher_run_id=runtime_context.publisher_run_id if runtime_context else None,
            )
            logger.info(
                "Raw-object publication markers written dataset=%s publication_scope=%s count=%d",
                spec.dataset_name,
                publication_scope,
                len(successful),
            )


##############################
# Post-Lock Filtering
##############################


def _filter_scope_results_after_lock(
    *,
    scope_results: list[AcquiredRawObject],
    store: RawObjectStore,
    pubtrack: PublicationTracker,
    spec: DatasetPublisherSpec,
    publication_scope: str,
) -> list[AcquiredRawObject]:
    unpublished_results = pubtrack.filter_unpublished(scope_results)
    already_published_count = len(scope_results) - len(unpublished_results)

    current_results, stale_count, missing_stale_count = store.filter_current_versions(unpublished_results)
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


##############################
# Batch Publication
##############################


def _publish_snapshot_scope_batch(
    *,
    scope_results: list[AcquiredRawObject],
    ctx: PublishContext,
    publish_one: Callable[[AcquiredRawObject, PublishContext], PublishResult],
    run_state: PipelineRunState,
) -> list[AcquiredRawObject]:
    successful: list[tuple[AcquiredRawObject, PublishResult]] = []

    try:
        with ctx.prep_ctx.session.transaction():
            for raw_object in scope_results:
                result = publish_one(raw_object, ctx)
                if not result.success:
                    raise RuntimeError("Snapshot batch publish returned unsuccessful result")
                successful.append((raw_object, result))
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

    for raw_object, result in successful:
        _record_success(run_state, raw_object, result)

    return [raw_object for raw_object, _ in successful]


def _publish_per_object(
    *,
    scope_results: list[AcquiredRawObject],
    ctx: PublishContext,
    publish_one: Callable[[AcquiredRawObject, PublishContext], PublishResult],
    run_state: PipelineRunState,
) -> list[AcquiredRawObject]:
    successful: list[AcquiredRawObject] = []

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
    raw_object: AcquiredRawObject,
    result: PublishResult,
) -> None:
    source_date = result.source_date or str(raw_object.identity_key.get("source_date", "unknown"))
    run_state.success += 1
    run_state.successful_results.append(raw_object)
    run_state.per_day_success[source_date] += 1


def _mark_successful_results_published(
    *,
    publication_scope: str,
    successful_results: list[AcquiredRawObject],
    pubtrack: PublicationTracker,
    publisher_run_id: str | None = None,
) -> None:
    context = PublicationContext(
        publication_scope=publication_scope,
        publisher_run_id=publisher_run_id,
    )
    pubtrack.mark_published_many(
        successful_results,
        context=context,
    )


##############################
# Helpers
##############################


def _group_by_publication_scope(
    spec: DatasetPublisherSpec,
    results: Iterable[AcquiredRawObject],
) -> dict[str, list[AcquiredRawObject]]:
    grouped: dict[str, list[AcquiredRawObject]] = defaultdict(list)
    for result in results:
        grouped[spec.scope_for(result.identity_key)].append(result)
    return {scope: grouped[scope] for scope in sorted(grouped)}


def _source_date_for_scope(
    publication_scope: str,
    results: list[AcquiredRawObject],
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
