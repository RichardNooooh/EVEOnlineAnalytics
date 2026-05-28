"""High-level cache for downloading and tracking batch archive/file-object sources.

Designed for everef.net bulk archives and similar file-object sources.
Not intended for streaming or REST API pagination sources (use dlt for those).

``Cache.get()`` resolution path (modules involved):

  Cache.get()
    ├─ _plan() -> _base_plan()
    │    └─ identity.py      — normalize_source_path, resolve_identity_key,
    │                           hash_identity_key
    │    └─ plans.py          — BaseFetchPlan, FetchPlan union type
    │    └─ ledger/plans.py   — FetchPlanResolver (ledger lookup)
    │         └─ ledger/reader.py  — RawObjectReader (SQL reads)
    │              └─ ledger/types.py — RawObjectRef, RawObjectEntry,
    │                                    RawObjectVersion
    │
    ├─ ResolvedFetchPlan path:
    │    ├─ _try_snapshot_local_hit()
    │    │    └─ paths.py   — build_snapshot_path
    │    └─ _fetch_with_revalidation()
    │         ├─ client.py  — HttpRawObjectClient (conditional GET)
    │         │    └─ client_types.py — ReadResult, ModifiedRead, etc.
    │         └─ _record_store()
    │              ├─ paths.py        — build_final_path, detect_storage_encoding
    │              ├─ ledger/writer.py — RawObjectWriter.rotate_version
    │              │    └─ ledger/types.py — RotateVersionResult
    │              └─ publishing.py    — PublicationTracker (via Cache.pubtrack)
    │
    └─ UnresolvedFetchPlan path:
         └─ (same as _record_store, no revalidation)

Output: CacheResult with status HIT (local) or STORED (downloaded).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from ingest.cache.client import HttpRawObjectClient
from ingest.cache.identity import (
    hash_identity_key,
    normalize_source_path,
    normalize_source_relative_path,
    resolve_identity_key,
)
from ingest.cache.ledger import RawObjectLedger
from ingest.cache.client_types import (
    ModifiedRead,
    ReadResult,
    ReadStatus,
    RevalidationMetadata,
)
from ingest.cache.ledger.types import RawObjectRef
from ingest.cache.models import (
    CacheObject,
    CacheResult,
    CacheResultStatus,
    GetMode,
)
from ingest.cache.primitives import UpdateMode
from ingest.cache.plans import (
    BaseFetchPlan,
    FetchPlan,
    ResolvedFetchPlan,
    UnresolvedFetchPlan,
)
from ingest.cache.paths import (
    build_final_path,
    build_snapshot_path,
    build_temp_path,
    detect_storage_encoding,
    validate_path_segment,
)
from ingest.cache.publishing import PublicationTracker
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
        self._dataset_name = validate_path_segment(dataset_name, field_name="dataset_name")
        if not isinstance(update_mode, UpdateMode):
            raise TypeError("update_mode must be an UpdateMode")
        self._update_mode = update_mode
        self._source_name = validate_path_segment(source_name, field_name="source_name")
        self._raw_root = Path(raw_root)
        self._client = client or HttpRawObjectClient()
        self._ledger = ledger or RawObjectLedger(ledger_url=ledger_url)
        self._pubtrack: PublicationTracker | None = None

    def __enter__(self) -> Cache:
        self._pubtrack = PublicationTracker(ledger=self._ledger)
        self._pubtrack.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._pubtrack is not None:
            self._pubtrack.__exit__(exc_type, exc, tb)
            self._pubtrack = None
        self._ledger.close()
        self._client.close()

    @property
    def pubtrack(self) -> PublicationTracker:
        if self._pubtrack is None:
            raise RuntimeError("Cache must be entered before accessing pubtrack")
        return self._pubtrack

    def get(
        self,
        cache_object: CacheObject,
        *,
        plan: FetchPlan | None = None,
    ) -> CacheResult:
        """Fetch one raw object and return its current local version.

        Snapshot objects are reused from disk without remote reads once cached. Mutable
        objects use ``ETag`` or ``Last-Modified`` headers to avoid downloading unchanged
        files.

        Resolution dispatch::

            get()
              ├─ _handle_resolved()                # plan has ledger state
               │    ├─ _try_snapshot_local_hit()    # SNAPSHOT + file exists -> HIT
              │    └─ _fetch_with_revalidation()   # conditional GET -> HIT or STORED
              └─ _handle_unresolved()              # no ledger state -> STORED

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
                    identity_key={"source_date": "2026-01-01"},
                )
            )
            if result.changed:
                print("new file", result.path)
            ```
        """

        plan = plan or self._plan(cache_object)
        if isinstance(plan, ResolvedFetchPlan):
            return self._handle_resolved(plan)
        return self._handle_unresolved(plan)

    def _handle_unresolved(self, plan: UnresolvedFetchPlan) -> CacheResult:
        """No ledger state; must fetch unconditionally."""
        read_result = self._read_source(plan, request_headers={})
        # Some origin servers return 304 even for unconditional requests
        # (misconfigured CDN, stale cache layers). When there's no ledger
        # state, a 304 is meaningless — re-fetch unconditionally.
        if read_result.status is ReadStatus.NOT_MODIFIED:
            logger.info(
                "not-modified response but no ledger state; re-reading source_url=%s",
                plan.source_url,
            )
            read_result = self._read_source(plan, request_headers={})
        return self._record_store(plan, _ensure_downloaded(read_result))

    def _handle_resolved(self, plan: ResolvedFetchPlan) -> CacheResult:
        """Try local cache hit, fall back to conditional fetch."""
        hit = self._try_snapshot_local_hit(plan)
        if hit is not None:
            return hit
        return self._fetch_with_revalidation(plan)

    def _try_snapshot_local_hit(self, plan: ResolvedFetchPlan) -> CacheResult | None:
        """SNAPSHOT with cached file on disk -> HIT, no remote call."""
        if plan.update_mode is UpdateMode.SNAPSHOT and _file_exists(plan.current_version.local_path):
            return self._record_hit(plan)
        return None

    def _fetch_with_revalidation(self, plan: ResolvedFetchPlan) -> CacheResult:
        """Conditional GET; record HIT on 304 or STORED on 200.

        This is the full revalidation path for resolved plans: send conditional
        headers, then either confirm a cache hit (304) or download and store a
        new version (200).
        """
        read_result = self._read_source(
            plan,
            request_headers=_request_headers_for(plan, plan.update_mode),
        )
        if read_result.status is ReadStatus.NOT_MODIFIED:
            if _file_exists(plan.current_version.local_path):
                return self._record_hit(plan, read_result=read_result)
            logger.info(
                "not-modified response but local state incomplete; re-reading source_url=%s",
                plan.source_url,
            )
            read_result = self._read_source(plan, request_headers={})
        return self._record_store(plan, _ensure_downloaded(read_result))

    def _read_source(
        self,
        plan: BaseFetchPlan,
        *,
        request_headers: Mapping[str, str],
    ) -> ReadResult:
        return self._client.read(
            source_url=plan.source_url,
            request_headers=dict(request_headers),
            temp_path=plan.temp_path,
        )

    def get_many(
        self,
        objects: Iterable[CacheObject],
        *,
        mode: GetMode = GetMode.CHANGED,
    ) -> list[CacheResult]:
        """Fetch objects and return results filtered by *mode*.

        Args:
            objects: Source objects to fetch.
            mode: ``CHANGED`` (default) — return only newly downloaded versions.
                  ``ALL`` — return every result (hits + stores).
                  ``UNPUBLISHED`` — return versions not yet marked as published.

        Returns:
            List of ``CacheResult`` filtered by the selected mode.

        Example:
            ```python
            results = cache.get_many(objects, mode=GetMode.ALL)
            changed = cache.get_many(objects)
            unpublished = cache.get_many(objects, mode=GetMode.UNPUBLISHED)
            ```
        """
        object_list = list(objects)
        plans = self._plan_many(object_list)

        results: list[CacheResult] = []
        for cache_object, plan in zip(object_list, plans, strict=True):
            result = self.get(cache_object, plan=plan)
            if mode is GetMode.CHANGED and not result.changed:
                continue
            results.append(result)

        if mode is not GetMode.UNPUBLISHED:
            return results

        published_versions = self.pubtrack.filter_published(results)
        return [
            result
            for result in results
            if (result.raw_object.ref.identity_hash, result.version.sha256) not in published_versions
        ]

    def _record_hit(
        self,
        plan: ResolvedFetchPlan,
        *,
        read_result: ReadResult | None = None,
    ) -> CacheResult:
        checked_at = read_result.fetched_at if read_result is not None else datetime.now(UTC)
        with self._ledger.transaction() as tx:
            raw_object = tx.writer.touch_raw_object(
                ref=plan.ref,
                checked_at=checked_at,
                revalidation=_revalidation_for_hit(plan, read_result),
            )
        return CacheResult(
            status=CacheResultStatus.HIT,
            raw_object=raw_object,
            version=plan.current_version,
        )

    def _record_store(self, plan: BaseFetchPlan, read_result: ModifiedRead) -> CacheResult:
        final_path = build_final_path(
            raw_root=self._raw_root,
            plan=plan,
            fetched_at=read_result.fetched_at,
            sha256=read_result.sha256,
        )
        final_path.parent.mkdir(parents=True, exist_ok=True)
        Path(read_result.temp_path).replace(final_path)

        try:
            with self._ledger.transaction() as tx:
                stored = tx.writer.rotate_version(
                    ref=plan.ref,
                    source_url=plan.source_url,
                    fetched_at=read_result.fetched_at,
                    revalidation=read_result.revalidation,
                    sha256=read_result.sha256,
                    local_path=str(final_path),
                    storage_encoding=detect_storage_encoding(final_path),
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

    def _plan(self, cache_object: CacheObject) -> FetchPlan:
        base_plan = self._base_plan(cache_object)

        with self._ledger.transaction() as tx:
            return tx.resolver.resolve_fetch_plan(base_plan)

    def _plan_many(self, cache_objects: Iterable[CacheObject]) -> list[FetchPlan]:
        base_plans = [self._base_plan(cache_object) for cache_object in cache_objects]
        with self._ledger.transaction() as tx:
            return tx.resolver.resolve_fetch_plans(base_plans)

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

        ref = RawObjectRef(
            source_name=self._source_name,
            dataset_name=self._dataset_name,
            identity_hash=identity_hash,
            identity_key=resolved_identity_key,
            update_mode=self._update_mode,
        )
        return BaseFetchPlan(
            ref=ref,
            source_url=cache_object.source_url,
            source_relative_path=source_relative_path,
            update_mode=self._update_mode,
            identity_key=resolved_identity_key,
            temp_path=str(build_temp_path(raw_root=self._raw_root, ref=ref)),
        )


def _current_local_path(plan: FetchPlan, *, raw_root: Path) -> str | None:
    if isinstance(plan, ResolvedFetchPlan):
        return plan.current_version.local_path
    if plan.update_mode is UpdateMode.SNAPSHOT:
        return str(build_snapshot_path(raw_root=raw_root, plan=plan))
    return None


def _file_exists(path: str | None) -> bool:
    return path is not None and Path(path).exists()


def _request_headers_for(plan: FetchPlan, update_mode: UpdateMode) -> Mapping[str, str]:
    if update_mode is not UpdateMode.MUTABLE or not isinstance(plan, ResolvedFetchPlan):
        return {}
    return plan.raw_object.revalidation.request_headers()


def _revalidation_for_hit(plan: ResolvedFetchPlan, read_result: ReadResult | None) -> RevalidationMetadata:
    if read_result is None:
        return plan.raw_object.revalidation
    return read_result.revalidation


def _ensure_downloaded(read_result: ReadResult) -> ModifiedRead:
    if read_result.status is ReadStatus.MODIFIED:
        assert isinstance(read_result, ModifiedRead)
        return read_result
    raise RuntimeError("client returned unexpected outcome without download")
