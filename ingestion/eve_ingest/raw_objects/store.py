"""High-level cache for downloading and tracking batch archive/file-object sources.

Designed for everef.net bulk archives and similar file-object sources.
Not intended for streaming or REST API pagination sources (use dlt for those).

``RawObjectStore.get()`` resolution path::

  get()
    ├─ _build_plan()           → FetchPlan (no ledger call)
    ├─ _load_current_state()   → CurrentRawObjectState | None
    └─ _get_from_plan()
         ├─ state is None        → _fetch_new()          → STORED
         ├─ snapshot + file OK   → _record_hit()          → HIT
         └─ mutable / no hit     → _revalidate_or_store() → HIT or STORED

Output: CacheResult with status HIT (local) or STORED (downloaded).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

import logging

from eve_ingest.raw_objects.http_client import HttpRawObjectClient
from eve_ingest.raw_objects.identity import (
    hash_identity_key,
    normalize_source_path,
    normalize_source_relative_path,
    resolve_identity_key,
)
from eve_ingest.raw_objects.ledger import RawObjectLedger
from eve_ingest.raw_objects.http_models import (
    ModifiedRead,
    ReadResult,
    ReadStatus,
    RevalidationMetadata,
)
from eve_ingest.raw_objects.ledger.models import CurrentRawObjectState, RawObjectEntry, RawObjectRef
from eve_ingest.raw_objects.models import (
    CacheObject,
    CacheResult,
    CacheResultStatus,
    GetMode,
)
from eve_ingest.raw_objects.primitives import UpdateMode
from eve_ingest.raw_objects.fetch_plan import FetchPlan
from eve_ingest.raw_objects.paths import (
    build_final_path,
    build_temp_path,
    detect_storage_encoding,
    validate_path_segment,
)
from eve_ingest.raw_objects.publishing import PublicationTracker
from eve_ingest.util import DEFAULT_RAW_LEDGER_URL, DEFAULT_RAW_ROOT

logger = logging.getLogger("eve_ingest.raw_objects")


class RawObjectStore:
    """Download and track raw source files before publication.

    Example:
        ```python
        from eve_ingest.raw_objects import RawObjectStore, CacheObject, UpdateMode

        with RawObjectStore(
            dataset_name="market-history",
            update_mode=UpdateMode.MUTABLE,
            raw_root="/data/raw",
            ledger_url=ledger_url,
        ) as store:
            result = store.get(
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
        raw_download_workers: int = 4,
        client: HttpRawObjectClient | None = None,
        ledger: RawObjectLedger | None = None,
    ) -> None:
        """Create a new RawObjectStore instance.

        Args:
            dataset_name: Logical dataset name used for path and ledger grouping.
                Must be a safe path segment (no ``/`` or ``\\``).
            update_mode: Cache policy. ``SNAPSHOT`` trusts local files forever;
                ``MUTABLE`` revalidates with conditional requests.
            source_name: Origin label (default ``everef``). Used for path
                segmentation and ledger grouping.
            raw_root: Root directory where downloaded files are stored.
            ledger_url: PostgreSQL URL for the ledger database.
            raw_download_workers: Maximum concurrent raw object downloads. Only
                applies when using the default HTTP client.
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
        if raw_download_workers < 1:
            raise ValueError("raw_download_workers must be at least 1")
        self._raw_download_workers = raw_download_workers
        self._has_injected_client = client is not None
        self._client = client or HttpRawObjectClient()
        self._ledger = ledger or RawObjectLedger(ledger_url=ledger_url)
        self._pubtrack: PublicationTracker | None = None

    def __enter__(self) -> RawObjectStore:
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
    def ledger(self) -> RawObjectLedger:
        return self._ledger

    @property
    def pubtrack(self) -> PublicationTracker:
        if self._pubtrack is None:
            raise RuntimeError("RawObjectStore must be entered before accessing pubtrack")
        return self._pubtrack

    # ── public API ──────────────────────────────────────────────────────────

    def get(self, cache_object: CacheObject) -> CacheResult:
        """Fetch one raw object and return its current local version.

        Snapshot objects are reused from disk without remote reads once cached. Mutable
        objects use ``ETag`` or ``Last-Modified`` headers to avoid downloading unchanged
        files.

        Args:
            cache_object: Description of the source object to fetch.

        Returns:
            ``CacheResult`` with status ``HIT`` or ``STORED``.

        Example:
            ```python
            result = store.get(
                CacheObject(
                    source_url="https://data.everef.net/market-orders/history/2026/file.csv.bz2",
                    identity_key={"source_date": "2026-01-01"},
                )
            )
            if result.changed:
                print("new file", result.path)
            ```
        """
        plan = self._build_plan(cache_object)
        state = self._load_current_state(plan.ref)
        return self._get_from_plan(plan, state)

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
            results = store.get_many(objects, mode=GetMode.ALL)
            changed = store.get_many(objects)
            unpublished = store.get_many(objects, mode=GetMode.UNPUBLISHED)
            ```
        """
        object_list = list(objects)
        plans = [self._build_plan(obj) for obj in object_list]
        states_by_hash = self._load_current_states([plan.ref for plan in plans])

        fetched_results = self._get_many_from_plans(plans, states_by_hash)
        results: list[CacheResult] = []
        for result in fetched_results:
            if mode is GetMode.CHANGED and not result.changed:
                continue
            results.append(result)

        hit_count = sum(1 for r in results if r.status is CacheResultStatus.HIT)
        stored_count = sum(1 for r in results if r.status is CacheResultStatus.STORED)

        if mode is GetMode.UNPUBLISHED:
            published_versions = self.pubtrack.filter_published(results)
            filtered = [
                result
                for result in results
                if (result.raw_object.ref.identity_hash, result.version.sha256) not in published_versions
            ]
            logger.info(
                "RawObjectStore acquire_many source=%s dataset=%s mode=%s requested=%d result_count=%d hit_count=%d stored_count=%d unpublished_count=%d",
                self._source_name,
                self._dataset_name,
                mode,
                len(object_list),
                len(results),
                hit_count,
                stored_count,
                len(filtered),
            )
            return filtered

        logger.info(
            "RawObjectStore acquire_many source=%s dataset=%s mode=%s requested=%d result_count=%d hit_count=%d stored_count=%d",
            self._source_name,
            self._dataset_name,
            mode,
            len(object_list),
            len(results),
            hit_count,
            stored_count,
        )
        return results

    def acquire_many(self, objects: Iterable[CacheObject]) -> list[CacheResult]:
        """Acquire raw objects from cache or remote, returning all results.

        Unlike get_many(), this returns every result (HIT + STORED) without
        filtering by mode. Use PublicationRegistry for publication filtering.
        """
        return self.get_many(objects, mode=GetMode.ALL)

    def filter_current_versions(self, results: list[CacheResult]) -> tuple[list[CacheResult], int, int]:
        """Filter mutable results to current versions, returning (current, stale_count, missing_stale_count)."""
        mutable_results = [result for result in results if result.update_mode is UpdateMode.MUTABLE]
        if not mutable_results:
            return results, 0, 0

        current_states = self.load_current_states_for_results(mutable_results)
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

    def load_current_states_for_results(
        self,
        results: Iterable[CacheResult],
    ) -> dict[str, CurrentRawObjectState | None]:
        """Load latest ledger state for cached results selected before publication locks."""

        refs = [result.raw_object.ref for result in results]
        if not refs:
            return {}
        with self._ledger.transaction() as tx:
            return tx.reader.load_current_states(refs=refs)

    # ── ledger state loading ────────────────────────────────────────────────

    def _load_current_state(self, ref: RawObjectRef) -> CurrentRawObjectState | None:
        with self._ledger.transaction() as tx:
            return tx.reader.load_current_states(refs=[ref]).get(ref.identity_hash)

    def _load_current_states(self, refs: list[RawObjectRef]) -> dict[str, CurrentRawObjectState | None]:
        if not refs:
            return {}
        with self._ledger.transaction() as tx:
            return tx.reader.load_current_states(refs=refs)

    # ── workflow ────────────────────────────────────────────────────────────

    def _get_from_plan(
        self,
        plan: FetchPlan,
        state: CurrentRawObjectState | None,
        *,
        client: HttpRawObjectClient | None = None,
    ) -> CacheResult:
        if state is None:
            return self._fetch_new(plan, client=client)

        self._require_update_mode_match(state.raw_object)
        if self._can_use_snapshot_local_hit(plan, state):
            return self._record_hit(plan, state)

        return self._revalidate_or_store(plan, state, client=client)

    def _get_many_from_plans(
        self,
        plans: list[FetchPlan],
        states_by_hash: dict[str, CurrentRawObjectState | None],
    ) -> list[CacheResult]:
        if self._raw_download_workers <= 1 or self._has_injected_client:
            return [self._get_from_plan(plan, states_by_hash.get(plan.ref.identity_hash)) for plan in plans]

        def fetch_one(plan: FetchPlan) -> CacheResult:
            client = HttpRawObjectClient()
            try:
                return self._get_from_plan(
                    plan,
                    states_by_hash.get(plan.ref.identity_hash),
                    client=client,
                )
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=self._raw_download_workers) as executor:
            return list(executor.map(fetch_one, plans))

    def _require_update_mode_match(self, raw_object_entry: RawObjectEntry) -> None:
        if raw_object_entry.ref.update_mode is not self._update_mode:
            raise ValueError(
                "raw object update_mode mismatch: "
                f"stored={raw_object_entry.ref.update_mode.value} requested={self._update_mode.value}"
            )

    def _fetch_new(self, plan: FetchPlan, *, client: HttpRawObjectClient | None = None) -> CacheResult:
        read_result = self._read_source(plan, request_headers={}, client=client)
        if read_result.status is ReadStatus.NOT_MODIFIED:
            logger.info(
                "not-modified response but no ledger state; re-reading source_url=%s",
                plan.source_url,
            )
            read_result = self._read_source(plan, request_headers={}, client=client)
        return self._record_store(plan, _ensure_downloaded(read_result))

    def _can_use_snapshot_local_hit(
        self,
        plan: FetchPlan,
        state: CurrentRawObjectState,
    ) -> bool:
        return plan.ref.update_mode is UpdateMode.SNAPSHOT and _file_exists(state.current_version.local_path)

    def _revalidate_or_store(
        self,
        plan: FetchPlan,
        state: CurrentRawObjectState,
        *,
        client: HttpRawObjectClient | None = None,
    ) -> CacheResult:
        read_result = self._read_source(
            plan,
            request_headers=_request_headers_for(state, plan.ref.update_mode),
            client=client,
        )
        if read_result.status is ReadStatus.NOT_MODIFIED:
            if _file_exists(state.current_version.local_path):
                return self._record_hit(plan, state, read_result=read_result)
            logger.info(
                "not-modified response but local state incomplete; re-reading source_url=%s",
                plan.source_url,
            )
            read_result = self._read_source(plan, request_headers={}, client=client)
        return self._record_store(plan, _ensure_downloaded(read_result))

    def _read_source(
        self,
        plan: FetchPlan,
        *,
        request_headers: Mapping[str, str],
        client: HttpRawObjectClient | None = None,
    ) -> ReadResult:
        active_client = client or self._client
        return active_client.read(
            source_url=plan.source_url,
            request_headers=dict(request_headers),
            temp_path=plan.temp_path,
        )

    # ── record helpers ──────────────────────────────────────────────────────

    def _record_hit(
        self,
        plan: FetchPlan,
        state: CurrentRawObjectState,
        *,
        read_result: ReadResult | None = None,
    ) -> CacheResult:
        checked_at = read_result.fetched_at if read_result is not None else datetime.now(UTC)
        logger.debug(
            "RawObjectStore hit dataset=%s identity_hash=%s version=%d path=%s",
            plan.ref.dataset_name,
            plan.ref.identity_hash,
            state.current_version.version_number,
            state.current_version.local_path,
        )
        with self._ledger.transaction() as tx:
            raw_object = tx.writer.touch_raw_object(
                ref=plan.ref,
                checked_at=checked_at,
                revalidation=_revalidation_for_hit(state, read_result),
            )
        return CacheResult(
            status=CacheResultStatus.HIT,
            raw_object=raw_object,
            version=state.current_version,
        )

    def _record_store(self, plan: FetchPlan, read_result: ModifiedRead) -> CacheResult:
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

        logger.info(
            "Stored raw object dataset=%s identity_hash=%s version=%d content_length=%s sha256_prefix=%s path=%s",
            plan.ref.dataset_name,
            plan.ref.identity_hash,
            stored.version.version_number,
            read_result.revalidation.content_length,
            read_result.sha256[:16],
            final_path,
        )

        for stale_version in stored.stale_versions:
            if stale_version.local_path != stored.version.local_path:
                Path(stale_version.local_path).unlink(missing_ok=True)

        return CacheResult(
            status=CacheResultStatus.STORED,
            raw_object=stored.raw_object,
            version=stored.version,
        )

    # ── plan construction ───────────────────────────────────────────────────

    def _build_plan(self, cache_object: CacheObject) -> FetchPlan:
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
        return FetchPlan(
            ref=ref,
            source_url=cache_object.source_url,
            source_relative_path=source_relative_path,
            temp_path=str(build_temp_path(raw_root=self._raw_root, ref=ref)),
        )


# ── module-level helpers ───────────────────────────────────────────────


def _file_exists(path: str | None) -> bool:
    return path is not None and Path(path).exists()


def _request_headers_for(state: CurrentRawObjectState, update_mode: UpdateMode) -> Mapping[str, str]:
    if update_mode is not UpdateMode.MUTABLE:
        return {}
    return state.raw_object.revalidation.request_headers()


def _revalidation_for_hit(state: CurrentRawObjectState, read_result: ReadResult | None) -> RevalidationMetadata:
    if read_result is None:
        return state.raw_object.revalidation
    return read_result.revalidation


def _ensure_downloaded(read_result: ReadResult) -> ModifiedRead:
    if read_result.status is ReadStatus.MODIFIED:
        assert isinstance(read_result, ModifiedRead)
        return read_result
    raise RuntimeError("client returned unexpected outcome without download")
