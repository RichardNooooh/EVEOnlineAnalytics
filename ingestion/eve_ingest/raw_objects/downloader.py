"""Downloader for raw objects — HTTP fetch, conditional revalidation, and ledger recording."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import logging

from eve_ingest.raw_objects.fetch_plan import FetchPlan
from eve_ingest.raw_objects.http_client import HttpRawObjectClient
from eve_ingest.raw_objects.http_models import (
    ModifiedRead,
    ReadResult,
    ReadStatus,
)
from eve_ingest.raw_objects.ledger import RawObjectLedger
from eve_ingest.raw_objects.ledger.models import CurrentRawObjectState
from eve_ingest.raw_objects.models import AcquiredRawObject, AcquisitionStatus
from eve_ingest.raw_objects.file_store import RawObjectFileStore
from eve_ingest.raw_objects.paths import build_final_path, detect_storage_encoding
from eve_ingest.raw_objects.store_helpers import (
    ensure_downloaded,
    file_exists,
    request_headers_for,
    revalidation_for_hit,
)

logger = logging.getLogger(__name__)


class RawObjectDownloader:
    """HTTP download, conditional revalidation, and ledger recording for raw objects."""

    def __init__(
        self,
        *,
        client: HttpRawObjectClient,
        owns_client: bool,
        raw_download_workers: int,
        ledger: RawObjectLedger,
        file_store: RawObjectFileStore,
    ) -> None:
        self._client = client
        self._owns_client = owns_client
        self._raw_download_workers = raw_download_workers
        self._ledger = ledger
        self._file_store = file_store

    def fetch_new(self, plan: FetchPlan, *, client: HttpRawObjectClient | None = None) -> AcquiredRawObject:
        read_result = self._read_source(plan, request_headers={}, client=client)
        if read_result.status is ReadStatus.NOT_MODIFIED:
            logger.info(
                "not-modified response but no ledger state; re-reading source_url=%s",
                plan.source_url,
            )
            read_result = self._read_source(plan, request_headers={}, client=client)
        return self._record_store(plan, ensure_downloaded(read_result))

    def revalidate_or_store(
        self,
        plan: FetchPlan,
        state: CurrentRawObjectState,
        *,
        client: HttpRawObjectClient | None = None,
    ) -> AcquiredRawObject:
        read_result = self._read_source(
            plan,
            request_headers=request_headers_for(state, plan.ref.update_mode),
            client=client,
        )
        if read_result.status is ReadStatus.NOT_MODIFIED:
            if file_exists(state.current_version.local_path):
                return self._record_hit(plan, state, read_result=read_result)
            logger.info(
                "not-modified response but local state incomplete; re-reading source_url=%s",
                plan.source_url,
            )
            read_result = self._read_source(plan, request_headers={}, client=client)
        return self._record_store(plan, ensure_downloaded(read_result))

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

    def _record_hit(
        self,
        plan: FetchPlan,
        state: CurrentRawObjectState,
        *,
        read_result: ReadResult | None = None,
    ) -> AcquiredRawObject:
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
                revalidation=revalidation_for_hit(state, read_result),
            )
        return AcquiredRawObject(
            status=AcquisitionStatus.HIT,
            raw_object=raw_object,
            version=state.current_version,
        )

    def _record_store(self, plan: FetchPlan, read_result: ModifiedRead) -> AcquiredRawObject:
        final_path = build_final_path(
            raw_root=self._file_store._raw_root,
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

        return AcquiredRawObject(
            status=AcquisitionStatus.STORED,
            raw_object=stored.raw_object,
            version=stored.version,
        )

    def get_many_from_plans(
        self,
        plans: list[FetchPlan],
        states_by_hash: dict[str, CurrentRawObjectState | None],
        get_from_plan: Callable,
    ) -> list[AcquiredRawObject]:
        if self._raw_download_workers <= 1 or not self._owns_client:
            return [get_from_plan(plan, states_by_hash.get(plan.ref.identity_hash)) for plan in plans]

        def fetch_one(plan: FetchPlan) -> AcquiredRawObject:
            client = HttpRawObjectClient()
            try:
                return get_from_plan(
                    plan,
                    states_by_hash.get(plan.ref.identity_hash),
                    client=client,
                )
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=self._raw_download_workers) as executor:
            return list(executor.map(fetch_one, plans))
