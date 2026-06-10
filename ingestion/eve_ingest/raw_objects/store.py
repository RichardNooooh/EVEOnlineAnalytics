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

from collections.abc import Iterable
from contextlib import ExitStack
from pathlib import Path
from types import TracebackType

import logging

from eve_ingest.raw_objects.downloader import RawObjectDownloader
from eve_ingest.raw_objects.file_store import RawObjectFileStore
from eve_ingest.raw_objects.http_client import HttpRawObjectClient
from eve_ingest.raw_objects.ledger import RawObjectLedger
from eve_ingest.raw_objects.models import (
    CacheObject,
    CacheResult,
    CacheResultStatus,
    GetMode,
)
from eve_ingest.raw_objects.primitives import UpdateMode
from eve_ingest.raw_objects.publishing import PublicationTracker
from eve_ingest.raw_objects.repository import RawObjectRepository
from eve_ingest.raw_objects.paths import validate_path_segment
from eve_ingest.util import DEFAULT_RAW_LEDGER_URL, DEFAULT_RAW_ROOT

logger = logging.getLogger("eve_ingest.raw_objects")


class RawObjectStore:
    """Download and track raw source files before publication.

    Orchestrates file-store, downloader, and repository sub-components.

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
        self._dataset_name = validate_path_segment(dataset_name, field_name="dataset_name")
        if not isinstance(update_mode, UpdateMode):
            raise TypeError("update_mode must be an UpdateMode")
        self._update_mode = update_mode
        self._source_name = validate_path_segment(source_name, field_name="source_name")
        self._raw_root = Path(raw_root)
        if raw_download_workers < 1:
            raise ValueError("raw_download_workers must be at least 1")
        self._raw_download_workers = raw_download_workers
        self._owns_client = client is None
        self._owns_ledger = ledger is None
        self._client = client if client is not None else HttpRawObjectClient()
        self._ledger = ledger if ledger is not None else RawObjectLedger(ledger_url=ledger_url)

        self._exit_stack = ExitStack()
        self._pubtrack: PublicationTracker | None = None

        self._file_store = RawObjectFileStore(
            raw_root=self._raw_root,
            source_name=self._source_name,
            dataset_name=self._dataset_name,
            update_mode=self._update_mode,
        )
        self._downloader = RawObjectDownloader(
            client=self._client,
            owns_client=self._owns_client,
            raw_download_workers=self._raw_download_workers,
            ledger=self._ledger,
            file_store=self._file_store,
        )
        self._repository = RawObjectRepository(
            ledger=self._ledger,
            update_mode=self._update_mode,
            downloader=self._downloader,
        )

    def __enter__(self) -> RawObjectStore:
        if self._owns_ledger:
            self._exit_stack.callback(self._ledger.close)
        if self._owns_client:
            self._exit_stack.callback(self._client.close)
        self._pubtrack = self._exit_stack.enter_context(PublicationTracker(ledger=self._ledger))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._pubtrack = None
        return self._exit_stack.__exit__(exc_type, exc, tb)

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
        plan = self._file_store.build_plan(cache_object)
        state = self._repository.load_current_state(plan.ref)
        return self._repository.get_from_plan(plan, state)

    def get_many(
        self,
        objects: Iterable[CacheObject],
        *,
        mode: GetMode = GetMode.CHANGED,
    ) -> list[CacheResult]:
        object_list = list(objects)
        plans = [self._file_store.build_plan(obj) for obj in object_list]
        states_by_hash = self._repository.load_current_states([plan.ref for plan in plans])

        fetched_results = self._downloader.get_many_from_plans(
            plans,
            states_by_hash,
            get_from_plan=self._repository.get_from_plan,
        )
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
        return self.get_many(objects, mode=GetMode.ALL)

    def filter_current_versions(self, results: list[CacheResult]) -> tuple[list[CacheResult], int, int]:
        return self._repository.filter_current_versions(results)

    def load_current_states_for_results(
        self,
        results: Iterable[CacheResult],
    ) -> dict[str, ...]:
        return self._repository.load_current_states_for_results(results)
