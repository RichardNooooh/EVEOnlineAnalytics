from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
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
    CacheObject,
    CacheResult,
    CacheResultStatus,
    FetchOutcome,
    FetchResult,
    IdentityKey,
    RawObjectEntry,
    RawObjectVersion,
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
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._ledger.close()
        self._client.close()

    def get(
        self,
        object: CacheObject,
        *,
        plan: RawObjectFetchPlan | None = None,
    ) -> CacheResult:
        """Fetch one raw object and return its current local version.

        Snapshot objects are reused from disk without remote reads once cached. Mutable
        objects use `ETag` or `Last-Modified` headers to avoid downloading unchanged
        files.

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

        plan = plan or self._plan(object)

        current_local_path = _current_local_path(plan)
        if plan.update_mode is UpdateMode.SNAPSHOT and _file_exists(current_local_path):
            return self._record_hit(plan)

        read_result = self._read_source(plan, request_headers=plan.request_headers)
        if read_result.outcome is FetchOutcome.NOT_MODIFIED and _file_exists(
            current_local_path
        ):
            return self._record_hit(plan, read_result=read_result)

        if read_result.outcome is FetchOutcome.NOT_MODIFIED:
            logger.info(
                "cached file missing after not-modified response; re-reading source_url=%s",
                plan.source_url,
            )
            read_result = self._read_source(plan, request_headers={})

        _ensure_downloaded(read_result)

        return self._record_store(plan, read_result)

    def _read_source(
        self,
        plan: RawObjectFetchPlan,
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
        plans_by_key = self._plan_many(object_list)

        results: list[CacheResult] = []
        for object in object_list:
            result = self.get(object, plan=plans_by_key[id(object)])
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
        publication_scope: str | None = None,
        publisher_run_id: str | None = None,
        published_at: datetime | None = None,
    ) -> None:
        """Record that one cached version has been published.

        Publication markers are idempotent for the same source, dataset, identity, and
        checksum.

        Example:
            ```python
            cache.mark_published(
                result,
                publication_scope="raw-market-history",
                publisher_run_id="airflow-run-42",
            )
            ```
        """

        with self._ledger.transaction() as tx:
            tx.mark_published(
                source_name=result.raw_object.source_name,
                dataset_name=result.raw_object.dataset_name,
                identity_hash=result.raw_object.identity_hash,
                sha256=result.version.sha256,
                version_id=result.version.id,
                published_at=published_at or datetime.now(UTC),
                publication_scope=publication_scope,
                publisher_run_id=publisher_run_id,
            )

    def mark_published_many(
        self,
        results: Iterable[CacheResult],
        *,
        publication_scope: str | None = None,
        publisher_run_id: str | None = None,
        published_at: datetime | None = None,
    ) -> None:
        """Record that many cached versions have been published.

        Example:
            ```python
            cache.mark_published_many(results, publication_scope="raw-market-orders")
            ```
        """

        marked_at = published_at or datetime.now(UTC)
        with self._ledger.transaction() as tx:
            for result in results:
                tx.mark_published(
                    source_name=result.raw_object.source_name,
                    dataset_name=result.raw_object.dataset_name,
                    identity_hash=result.raw_object.identity_hash,
                    sha256=result.version.sha256,
                    version_id=result.version.id,
                    published_at=marked_at,
                    publication_scope=publication_scope,
                    publisher_run_id=publisher_run_id,
                )

    def is_published(self, result: CacheResult) -> bool:
        """Return whether a cached version already has a publication marker.

        Example:
            ```python
            if not cache.is_published(result):
                publish(result.path)
            ```
        """

        with self._ledger.transaction() as tx:
            return tx.is_published(
                source_name=result.raw_object.source_name,
                dataset_name=result.raw_object.dataset_name,
                identity_hash=result.raw_object.identity_hash,
                sha256=result.version.sha256,
            )

    def _record_hit(
        self,
        plan: RawObjectFetchPlan,
        *,
        read_result: FetchResult | None = None,
    ) -> CacheResult:
        checked_at = (
            read_result.fetched_at if read_result is not None else datetime.now(UTC)
        )
        with self._ledger.transaction() as tx:
            raw_object = tx.touch_raw_object(
                source_name=plan.source_name,
                dataset_name=plan.dataset_name,
                identity_key=plan.identity_key,
                identity_hash=plan.identity_hash,
                update_mode=plan.update_mode,
                checked_at=checked_at,
                current_version=plan.current_version,
            )
        if plan.current_version is None:
            raise RuntimeError("current_version is required for cache hit")
        return CacheResult(
            status=CacheResultStatus.HIT,
            raw_object=raw_object,
            version=plan.current_version,
        )

    def _record_store(
        self, plan: RawObjectFetchPlan, read_result: FetchResult
    ) -> CacheResult:
        final_path = _build_final_path(
            raw_root=self._raw_root,
            plan=plan,
            fetched_at=read_result.fetched_at,
            sha256=read_result.sha256,
        )
        final_path.parent.mkdir(parents=True, exist_ok=True)
        Path(read_result.temp_path).replace(final_path)

        previous_versions: list[RawObjectVersion] = []
        version: RawObjectVersion | None = None
        try:
            with self._ledger.transaction() as tx:
                raw_object = tx.touch_raw_object(
                    source_name=plan.source_name,
                    dataset_name=plan.dataset_name,
                    identity_key=plan.identity_key,
                    identity_hash=plan.identity_hash,
                    update_mode=plan.update_mode,
                    checked_at=read_result.fetched_at,
                    current_version=plan.current_version,
                )
                version = RawObjectVersion(
                    id=uuid4().hex,
                    raw_object_id=raw_object.id,
                    source_url=plan.source_url,
                    fetched_at=read_result.fetched_at,
                    etag=read_result.etag,
                    last_modified=read_result.last_modified,
                    content_length=read_result.content_length,
                    sha256=read_result.sha256,
                    local_path=str(final_path),
                    storage_encoding=_detect_storage_encoding(final_path),
                )
                previous_versions = tx.list_versions(raw_object.id)
                tx.insert_version(version)
                raw_object = replace(
                    raw_object,
                    last_checked_at=read_result.fetched_at,
                    last_seen_etag=read_result.etag,
                    last_seen_last_modified=read_result.last_modified,
                    last_seen_content_length=read_result.content_length,
                )
        except Exception:
            final_path.unlink(missing_ok=True)
            raise

        if version is None:
            raise RuntimeError("stored version was not created")

        if previous_versions:
            with self._ledger.transaction() as tx:
                tx.delete_versions([stale.id for stale in previous_versions])
            for stale_version in previous_versions:
                if stale_version.local_path != version.local_path:
                    Path(stale_version.local_path).unlink(missing_ok=True)

        return CacheResult(
            status=CacheResultStatus.STORED,
            raw_object=raw_object,
            version=version,
        )

    def _plan(self, object: CacheObject) -> RawObjectFetchPlan:
        plan = self._base_plan(object)

        with self._ledger.transaction() as tx:
            raw_object = tx.load_raw_object(
                source_name=plan.source_name,
                dataset_name=plan.dataset_name,
                identity_hash=plan.identity_hash,
            )
            _require_update_mode(raw_object, plan.update_mode)
            current_version = (
                tx.load_latest_version(raw_object.id)
                if raw_object is not None
                else None
            )

        return replace(
            plan,
            request_headers=_build_request_headers(current_version, plan.update_mode),
            raw_object=raw_object,
            current_version=current_version,
        )

    def _plan_many(
        self, objects: Iterable[CacheObject]
    ) -> dict[int, RawObjectFetchPlan]:
        base_plans = [self._base_plan(object) for object in objects]
        grouped_plans: dict[tuple[str, str], list[RawObjectFetchPlan]] = {}
        for plan in base_plans:
            grouped_plans.setdefault((plan.source_name, plan.dataset_name), []).append(
                plan
            )

        resolved_plans: dict[int, RawObjectFetchPlan] = {}
        with self._ledger.transaction() as tx:
            for (source_name, dataset_name), plans in grouped_plans.items():
                raw_objects = tx.load_raw_objects(
                    source_name=source_name,
                    dataset_name=dataset_name,
                    identity_hashes=[plan.identity_hash for plan in plans],
                )
                current_versions = tx.load_latest_versions(
                    [raw_object.id for raw_object in raw_objects.values()]
                )
                for plan in plans:
                    raw_object = raw_objects.get(plan.identity_hash)
                    _require_update_mode(raw_object, plan.update_mode)
                    current_version = (
                        current_versions.get(raw_object.id)
                        if raw_object is not None
                        else None
                    )
                    resolved_plans[plan.object_key] = replace(
                        plan,
                        request_headers=_build_request_headers(
                            current_version, plan.update_mode
                        ),
                        raw_object=raw_object,
                        current_version=current_version,
                    )

        return resolved_plans

    def _base_plan(self, object: CacheObject) -> RawObjectFetchPlan:
        source_relative_path = (
            normalize_source_path(object.source_path)
            if object.source_path is not None
            else normalize_source_relative_path(object.source_url)
        )
        resolved_identity_key = resolve_identity_key(
            identity_key=object.identity_key,
            source_relative_path=source_relative_path,
        )
        identity_hash = hash_identity_key(resolved_identity_key)

        return RawObjectFetchPlan(
            object_key=id(object),
            source_name=self._source_name,
            dataset_name=self._dataset_name,
            source_url=object.source_url,
            source_relative_path=source_relative_path,
            update_mode=self._update_mode,
            identity_key=resolved_identity_key,
            identity_hash=identity_hash,
            request_headers={},
            temp_path=str(
                _build_temp_path(raw_root=self._raw_root, source_name=self._source_name)
            ),
            raw_object=None,
            current_version=None,
        )

    def _filter_published(self, results: Iterable[CacheResult]) -> set[tuple[str, str]]:
        result_list = list(results)
        grouped_results: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for result in result_list:
            grouped_results.setdefault(
                (result.raw_object.source_name, result.raw_object.dataset_name), []
            ).append((result.raw_object.identity_hash, result.version.sha256))

        published_versions: set[tuple[str, str]] = set()
        with self._ledger.transaction() as tx:
            for (source_name, dataset_name), versions in grouped_results.items():
                published_versions.update(
                    tx.filter_published(
                        source_name=source_name,
                        dataset_name=dataset_name,
                        versions=versions,
                    )
                )
        return published_versions


@dataclass(frozen=True)
class RawObjectFetchPlan:
    object_key: int
    source_name: str
    dataset_name: str
    source_url: str
    source_relative_path: str
    update_mode: UpdateMode
    identity_key: IdentityKey
    identity_hash: str
    request_headers: Mapping[str, str]
    temp_path: str
    raw_object: RawObjectEntry | None
    current_version: RawObjectVersion | None


def _build_request_headers(
    current_version: RawObjectVersion | None,
    update_mode: UpdateMode,
) -> Mapping[str, str]:
    if update_mode is not UpdateMode.MUTABLE or current_version is None:
        return {}
    if current_version.etag:
        return {"If-None-Match": current_version.etag}
    if current_version.last_modified:
        return {"If-Modified-Since": current_version.last_modified}
    return {}


def _require_update_mode(
    raw_object: RawObjectEntry | None, update_mode: UpdateMode
) -> None:
    if raw_object is None or raw_object.update_mode is update_mode:
        return
    raise ValueError(
        "raw object update_mode mismatch: "
        f"stored={raw_object.update_mode.value} requested={update_mode.value}"
    )


def _current_local_path(plan: RawObjectFetchPlan) -> str | None:
    return plan.current_version.local_path if plan.current_version else None


def _file_exists(path: str | None) -> bool:
    return path is not None and Path(path).exists()


def _ensure_downloaded(read_result: FetchResult) -> None:
    if read_result.outcome is not FetchOutcome.DOWNLOADED:
        raise RuntimeError("client returned unexpected outcome without download")
    if read_result.temp_path is None or read_result.sha256 is None:
        raise RuntimeError("downloaded client result must include temp_path and sha256")


def _build_temp_path(*, raw_root: Path, source_name: str) -> Path:
    source_name = _validate_path_segment(source_name, field_name="source_name")
    return raw_root / source_name / ".tmp" / f"{uuid4().hex}.download"


def _build_final_path(
    *,
    raw_root: Path,
    plan: RawObjectFetchPlan,
    fetched_at: datetime,
    sha256: str,
) -> Path:
    source_name = _validate_path_segment(plan.source_name, field_name="source_name")
    dataset_name = _validate_path_segment(plan.dataset_name, field_name="dataset_name")
    if plan.update_mode is UpdateMode.SNAPSHOT:
        return raw_root / source_name / Path(plan.source_relative_path)

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
