"""High-level cache for downloading and tracking raw source files.

``Cache`` coordinates HTTP reads, filesystem storage, and ledger bookkeeping
so that ingestion pipelines can fetch source objects, detect changes, and
publish only unseen versions.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from ingest.cache.client import HttpRawObjectClient
from ingest.cache.identity import (
    hash_identity_key,
    normalize_source_path,
    normalize_source_relative_path,
    resolve_identity_key,
)
from ingest.cache.ledger import RawObjectLedger
from ingest.cache.models import (
    BaseFetchPlan,
    CacheObject,
    CacheResult,
    CacheResultStatus,
    FetchOutcome,
    FetchResult,
    ModifiedResult,
    PublicationContext,
    RawObjectEntry,
    RevalidationMetadata,
    ResolvedFetchPlan,
    UpdateMode,
)
from ingest.util import DEFAULT_RAW_LEDGER_URL, DEFAULT_RAW_ROOT

logger = logging.getLogger("ingest.cache")


class Cache:
    """Download and track raw source files before publication.

    Example:
        ```python
        from ingest.cache import Cache, CacheObject, UpdateMode

        with Cache(
            dataset_name="market-history",
            update_mode=UpdateMode.MUTABLE,
            raw_root="/data/raw",
            ledger_url=ledger_url,
        ) as cache:
            result = cache.get(
                CacheObject(
                    source_url="https://data.everef.net/market-history/2026-01-01.csv.bz2",
                    identity_key={"source_date": "2026-01-01"},
                )
            )
            print(result.path)
        ```
    """

    def __init__(
        self,
        *,
        dataset_name: str,
        update_mode: UpdateMode,
        source_name: str = "everef",
        raw_root: str | Path = DEFAULT_RAW_ROOT,
        ledger_url: str = DEFAULT_RAW_LEDGER_URL,
        client: HttpRawObjectClient | None = None,
        ledger: RawObjectLedger | None = None,
    ) -> None:
        """Create a new cache instance.

        Args:
            dataset_name: Logical dataset name used for path and ledger grouping.
                Must be a safe path segment (no ``/`` or ``\\``).
            update_mode: Cache policy. ``SNAPSHOT`` trusts local files forever;
                ``MUTABLE`` revalidates with conditional requests.
            source_name: Origin label (default ``everef``). Used for path
                segmentation and ledger grouping.
            raw_root: Root directory where downloaded files are stored.
            ledger_url: PostgreSQL URL for the ledger database.
            client: Optional HTTP client override.  A default
                ``HttpRawObjectClient`` is created when omitted.
            ledger: Optional ledger override.  A default ``RawObjectLedger`` is
                created when omitted.

        Raises:
            TypeError: If ``update_mode`` is not an ``UpdateMode`` enum member.
            ValueError: If ``dataset_name`` or ``source_name`` contain path
                separators or are empty.
        """
        self._dataset_name = _validate_path_segment(
            dataset_name, field_name="dataset_name"
        )
        if not isinstance(update_mode, UpdateMode):
            raise TypeError("update_mode must be an UpdateMode")
        self._update_mode = update_mode
        self._source_name = _validate_path_segment(
            source_name, field_name="source_name"
        )
        self._raw_root = Path(raw_root)
        self._client = client or HttpRawObjectClient()
        self._ledger = ledger or RawObjectLedger(ledger_url=ledger_url)

    def __enter__(self) -> Cache:
        """Enter context manager.  Returns ``self``."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit context manager and close ledger and client connections."""
        self._ledger.close()
        self._client.close()

    def get(
        self,
        cache_object: CacheObject,
        *,
        plan: ResolvedFetchPlan | None = None,
    ) -> CacheResult:
        """Fetch one raw object and return its current local version.

        Snapshot objects are reused from disk without remote reads once cached. Mutable
        objects use ``ETag`` or ``Last-Modified`` headers to avoid downloading unchanged
        files.

        Args:
            cache_object: Description of the source object to fetch.
            plan: Optional pre-resolved fetch plan.  When omitted the plan is
                resolved from the ledger automatically.

        Returns:
            ``CacheResult`` with status ``HIT`` or ``STORED``.

        Raises:
            RuntimeError: If the client returns ``NOT_MODIFIED`` but the local
                file is missing and cannot be recovered.

        Example:
            ```python
            result = cache.get(
                CacheObject(
                    source_url="https://data.everef.net/market-orders/history/2026/file.csv.bz2",
                )
            )
            if result.changed:
                print("new file", result.path)
            ```
        """

        plan = plan or self._plan(cache_object)

        current_local_path = _current_local_path(plan, raw_root=self._raw_root)
        if plan.update_mode is UpdateMode.SNAPSHOT and _file_exists(current_local_path):
            if plan.current_version is not None:
                return self._record_hit(plan)
            logger.info(
                "cached file missing ledger state; re-reading source_url=%s",
                plan.source_url,
            )

        read_result = self._read_source(
            plan,
            request_headers=_request_headers_for(plan.raw_object, plan.update_mode),
        )
        if read_result.outcome is FetchOutcome.NOT_MODIFIED and _file_exists(
            current_local_path
        ):
            if plan.current_version is not None:
                return self._record_hit(plan, read_result=read_result)
            logger.info(
                "not-modified response missing ledger state; re-reading source_url=%s",
                plan.source_url,
            )
            read_result = self._read_source(plan, request_headers={})

        if read_result.outcome is FetchOutcome.NOT_MODIFIED:
            logger.info(
                "cached file missing after not-modified response; re-reading source_url=%s",
                plan.source_url,
            )
            read_result = self._read_source(plan, request_headers={})

        modified_result = _ensure_downloaded(read_result)

        return self._record_store(plan, modified_result)

    def _read_source(
        self,
        plan: BaseFetchPlan,
        *,
        request_headers: Mapping[str, str],
    ) -> FetchResult:
        return self._client.read(
            source_url=plan.source_url,
            request_headers=dict(request_headers),
            temp_path=plan.temp_path,
        )

    def _get_many(
        self,
        objects: Iterable[CacheObject],
        *,
        changed_only: bool = True,
        unpublished_only: bool = False,
    ) -> list[CacheResult]:
        object_list = list(objects)
        plans = self._plan_many(object_list)

        results: list[CacheResult] = []
        for cache_object, plan in zip(object_list, plans, strict=True):
            result = self.get(cache_object, plan=plan)
            if changed_only and not result.changed:
                continue
            results.append(result)

        if not unpublished_only:
            return results

        published_versions = self._filter_published(results)
        return [
            result
            for result in results
            if (result.raw_object.identity_hash, result.version.sha256)
            not in published_versions
        ]

    def get_all(self, objects: Iterable[CacheObject]) -> list[CacheResult]:
        """Fetch every requested object and return hits plus downloads.

        Args:
            objects: Source objects to fetch.

        Returns:
            List of ``CacheResult`` including both hits and stored versions.

        Example:
            ```python
            results = cache.get_all([
                CacheObject(source_url=url)
            ])
            ```
        """

        return self._get_many(objects, changed_only=False)

    def get_changed(self, objects: Iterable[CacheObject]) -> list[CacheResult]:
        """Fetch objects and return only newly downloaded versions.

        Args:
            objects: Source objects to fetch.

        Returns:
            Subset of ``CacheResult`` where ``status`` is ``STORED``.

        Example:
            ```python
            for result in cache.get_changed(requests):
                publish(result.path)
            ```
        """

        return self._get_many(objects)

    def get_unpublished(self, objects: Iterable[CacheObject]) -> list[CacheResult]:
        """Fetch objects and return versions not marked as published.

        Use this when retrying a publication job after files have already been cached.

        Args:
            objects: Source objects to fetch.

        Returns:
            ``CacheResult`` items that lack a publication marker for their
            current checksum.

        Example:
            ```python
            unpublished = cache.get_unpublished(requests)
            publish_many(unpublished)
            cache.mark_published_many(unpublished, publication_scope="raw-market-history")
            ```
        """

        return self._get_many(objects, changed_only=False, unpublished_only=True)

    def mark_published(
        self,
        result: CacheResult,
        *,
        context: PublicationContext | None = None,
    ) -> None:
        """Record that one cached version has been published.

        Publication markers are idempotent for the same source, dataset, identity, and
        checksum.

        Args:
            result: The cached version that was published.
            context: Optional publication scope and run id.  Defaults to an
                empty context with the current timestamp.

        Example:
            ```python
            cache.mark_published(
                result,
                context=PublicationContext(
                    publication_scope="raw-market-history",
                    publisher_run_id="airflow-run-42",
                ),
            )
            ```
        """

        ctx = context or PublicationContext()
        with self._ledger.transaction() as tx:
            tx.mark_published(
                ref=result.raw_object.ref,
                sha256=result.version.sha256,
                version_id=result.version.id,
                context=ctx,
            )

    def mark_published_many(
        self,
        results: Iterable[CacheResult],
        *,
        context: PublicationContext | None = None,
    ) -> None:
        """Record that many cached versions have been published.

        Args:
            results: Cached versions that were published.
            context: Optional publication scope and run id shared across all
                results.

        Example:
            ```python
            cache.mark_published_many(
                results,
                context=PublicationContext(publication_scope="raw-market-orders"),
            )
            ```
        """

        ctx = context or PublicationContext()
        with self._ledger.transaction() as tx:
            for result in results:
                tx.mark_published(
                    ref=result.raw_object.ref,
                    sha256=result.version.sha256,
                    version_id=result.version.id,
                    context=ctx,
                )

    def is_published(self, result: CacheResult) -> bool:
        """Return whether a cached version already has a publication marker.

        Args:
            result: The cached version to check.

        Returns:
            ``True`` when a marker exists for this source, dataset, identity,
            and checksum.

        Example:
            ```python
            if not cache.is_published(result):
                publish(result.path)
            ```
        """

        with self._ledger.transaction() as tx:
            return tx.is_published(
                ref=result.raw_object.ref,
                sha256=result.version.sha256,
            )

    def _record_hit(
        self,
        plan: ResolvedFetchPlan,
        *,
        read_result: FetchResult | None = None,
    ) -> CacheResult:
        if plan.current_version is None:
            raise RuntimeError("hit recording requires current_version")
        checked_at = (
            read_result.fetched_at if read_result is not None else datetime.now(UTC)
        )
        with self._ledger.transaction() as tx:
            raw_object = tx.touch_raw_object(
                definition=plan.definition,
                checked_at=checked_at,
                revalidation=_revalidation_for_hit(plan, read_result),
            )
        return CacheResult(
            status=CacheResultStatus.HIT,
            raw_object=raw_object,
            version=plan.current_version,
        )

    def _record_store(
        self, plan: ResolvedFetchPlan, read_result: ModifiedResult
    ) -> CacheResult:
        final_path = _build_final_path(
            raw_root=self._raw_root,
            plan=plan,
            fetched_at=read_result.fetched_at,
            sha256=read_result.sha256,
        )
        final_path.parent.mkdir(parents=True, exist_ok=True)
        Path(read_result.temp_path).replace(final_path)

        try:
            with self._ledger.transaction() as tx:
                stored = tx.replace_current_version(
                    definition=plan.definition,
                    source_url=plan.source_url,
                    fetched_at=read_result.fetched_at,
                    revalidation=read_result.revalidation,
                    sha256=read_result.sha256,
                    local_path=str(final_path),
                    storage_encoding=_detect_storage_encoding(final_path),
                )
        except Exception:
            final_path.unlink(missing_ok=True)
            raise

        for stale_version in stored.stale_versions:
            if stale_version.local_path != stored.version.local_path:
                Path(stale_version.local_path).unlink(missing_ok=True)

        return CacheResult(
            status=CacheResultStatus.STORED,
            raw_object=stored.raw_object,
            version=stored.version,
        )

    def _plan(self, cache_object: CacheObject) -> ResolvedFetchPlan:
        base_plan = self._base_plan(cache_object)

        with self._ledger.transaction() as tx:
            return tx.resolve_fetch_plan(base_plan)

    def _plan_many(
        self, cache_objects: Iterable[CacheObject]
    ) -> list[ResolvedFetchPlan]:
        base_plans = [self._base_plan(cache_object) for cache_object in cache_objects]
        with self._ledger.transaction() as tx:
            return tx.resolve_fetch_plans(base_plans)

    def _base_plan(self, cache_object: CacheObject) -> BaseFetchPlan:
        source_relative_path = (
            normalize_source_path(cache_object.source_path)
            if cache_object.source_path is not None
            else normalize_source_relative_path(cache_object.source_url)
        )
        resolved_identity_key = resolve_identity_key(
            identity_key=cache_object.identity_key,
            source_relative_path=source_relative_path,
        )
        identity_hash = hash_identity_key(resolved_identity_key)

        return BaseFetchPlan(
            source_name=self._source_name,
            dataset_name=self._dataset_name,
            source_url=cache_object.source_url,
            source_relative_path=source_relative_path,
            update_mode=self._update_mode,
            identity_key=resolved_identity_key,
            identity_hash=identity_hash,
            temp_path=str(
                _build_temp_path(raw_root=self._raw_root, source_name=self._source_name)
            ),
        )

    def _filter_published(self, results: Iterable[CacheResult]) -> set[tuple[str, str]]:
        result_list = list(results)
        grouped_results: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for result in result_list:
            grouped_results.setdefault(result.raw_object.ref.group_key, []).append(
                (result.raw_object.identity_hash, result.version.sha256)
            )

        published_versions: set[tuple[str, str]] = set()
        with self._ledger.transaction() as tx:
            for group_key, versions in grouped_results.items():
                published_versions.update(
                    tx.filter_published(
                        group_key=group_key,
                        versions=versions,
                    )
                )
        return published_versions


def _current_local_path(plan: ResolvedFetchPlan, *, raw_root: Path) -> str | None:
    if plan.current_version is not None:
        return plan.current_version.local_path
    if plan.update_mode is UpdateMode.SNAPSHOT:
        return str(_build_snapshot_path(raw_root=raw_root, plan=plan))
    return None


def _file_exists(path: str | None) -> bool:
    return path is not None and Path(path).exists()


def _request_headers_for(
    raw_object: RawObjectEntry | None, update_mode: UpdateMode
) -> Mapping[str, str]:
    if update_mode is not UpdateMode.MUTABLE or raw_object is None:
        return {}
    return raw_object.revalidation.request_headers()


def _revalidation_for_hit(
    plan: ResolvedFetchPlan, read_result: FetchResult | None
) -> RevalidationMetadata:
    if read_result is None:
        if plan.raw_object is not None:
            return plan.raw_object.revalidation
        return plan.current_version.revalidation
    return read_result.revalidation


def _ensure_downloaded(read_result: FetchResult) -> ModifiedResult:
    if read_result.outcome is FetchOutcome.MODIFIED:
        assert isinstance(read_result, ModifiedResult)
        return read_result
    raise RuntimeError("client returned unexpected outcome without download")


def _build_temp_path(*, raw_root: Path, source_name: str) -> Path:
    source_name = _validate_path_segment(source_name, field_name="source_name")
    return raw_root / source_name / ".tmp" / f"{uuid4().hex}.download"


def _build_final_path(
    *,
    raw_root: Path,
    plan: BaseFetchPlan,
    fetched_at: datetime,
    sha256: str,
) -> Path:
    if plan.update_mode is UpdateMode.SNAPSHOT:
        return _build_snapshot_path(raw_root=raw_root, plan=plan)

    source_name = _validate_path_segment(plan.source_name, field_name="source_name")
    dataset_name = _validate_path_segment(plan.dataset_name, field_name="dataset_name")

    basename = Path(plan.source_relative_path).name or f"{dataset_name}.bin"
    timestamp = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    return (
        raw_root
        / source_name
        / dataset_name
        / "objects"
        / plan.identity_hash
        / f"{timestamp}__{sha256[:12]}__{uuid4().hex[:8]}__{basename}"
    )


def _build_snapshot_path(*, raw_root: Path, plan: BaseFetchPlan) -> Path:
    source_name = _validate_path_segment(plan.source_name, field_name="source_name")
    return raw_root / source_name / Path(plan.source_relative_path)


def _detect_storage_encoding(path: Path) -> str:
    suffixes = [suffix.lstrip(".") for suffix in path.suffixes]
    if not suffixes:
        return "raw"
    return ".".join(suffixes)


def _validate_path_segment(value: str, *, field_name: str) -> str:
    if not value or value in {".", ".."}:
        raise ValueError(f"{field_name} must be a safe non-empty path segment")
    if "/" in value or "\\" in value:
        raise ValueError(f"{field_name} must not contain path separators")
    return value
