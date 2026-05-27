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
    ClientReadResult,
    IdentityKey,
    IdentityScalar,
    RawObject,
    RawObjectRequest,
    RawObjectResult,
    RawObjectStatus,
    RawObjectVersion,
    ReadOutcome,
    UpdateMode,
)
from ingest.util import DEFAULT_RAW_LEDGER_URL, DEFAULT_RAW_ROOT

logger = logging.getLogger("ingest.cache")


@dataclass(frozen=True)
class _RawObjectPlan:
    source_name: str
    dataset_name: str
    source_url: str
    source_relative_path: str
    update_mode: UpdateMode
    identity_key: IdentityKey
    identity_hash: str
    request_headers: Mapping[str, str]
    temp_path: str
    raw_object: RawObject | None
    current_version: RawObjectVersion | None


class RawObjectCache:
    def __init__(
        self,
        *,
        source_name: str,
        raw_root: str | Path,
        ledger_url: str,
        client: HttpRawObjectClient | None = None,
        ledger: RawObjectLedger | None = None,
    ) -> None:
        self._source_name = _validate_path_segment(
            source_name, field_name="source_name"
        )
        self._raw_root = Path(raw_root)
        self._client = client or HttpRawObjectClient()
        self._ledger = ledger or RawObjectLedger(ledger_url=ledger_url)

    @classmethod
    def open(
        cls,
        *,
        source_name: str = "everef",
        raw_root: str = DEFAULT_RAW_ROOT,
        ledger_url: str = DEFAULT_RAW_LEDGER_URL,
        client: HttpRawObjectClient | None = None,
        ledger: RawObjectLedger | None = None,
    ) -> RawObjectCache:
        return cls(
            source_name=source_name,
            raw_root=raw_root,
            ledger_url=ledger_url,
            client=client,
            ledger=ledger,
        )

    def __enter__(self) -> RawObjectCache:
        self._ledger.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._ledger.close()
        self._client.close()

    def _plan(
        self,
        *,
        source_name: str | None,
        dataset_name: str,
        source_url: str,
        update_mode: UpdateMode | str,
        source_path: str | None = None,
        identity_key: Mapping[str, IdentityScalar] | None = None,
    ) -> _RawObjectPlan:
        resolved_source_name = source_name or self._source_name
        resolved_mode = UpdateMode(update_mode)
        source_relative_path = (
            normalize_source_path(source_path)
            if source_path is not None
            else normalize_source_relative_path(source_url)
        )
        resolved_identity_key = resolve_identity_key(
            identity_key=identity_key,
            source_relative_path=source_relative_path,
        )
        identity_hash = hash_identity_key(resolved_identity_key)

        with self._ledger.transaction():
            raw_object = self._ledger.load_raw_object(
                source_name=resolved_source_name,
                dataset_name=dataset_name,
                identity_hash=identity_hash,
            )
            current_version = (
                self._ledger.load_latest_version(raw_object.id)
                if raw_object is not None
                else None
            )
            if raw_object is not None and raw_object.update_mode is not resolved_mode:
                raise ValueError(
                    "raw object update_mode mismatch: "
                    f"stored={raw_object.update_mode.value} requested={resolved_mode.value}"
                )

        return _RawObjectPlan(
            source_name=resolved_source_name,
            dataset_name=dataset_name,
            source_url=source_url,
            source_relative_path=source_relative_path,
            update_mode=resolved_mode,
            identity_key=resolved_identity_key,
            identity_hash=identity_hash,
            request_headers=_build_request_headers(current_version, resolved_mode),
            temp_path=str(
                _build_temp_path(
                    raw_root=self._raw_root, source_name=resolved_source_name
                )
            ),
            raw_object=raw_object,
            current_version=current_version,
        )

    def get(
        self,
        *,
        source_name: str | None = None,
        dataset_name: str,
        source_url: str,
        update_mode: UpdateMode | str,
        source_path: str | None = None,
        identity_key: Mapping[str, IdentityScalar] | None = None,
    ) -> RawObjectResult:
        plan = self._plan(
            source_name=source_name,
            dataset_name=dataset_name,
            source_url=source_url,
            source_path=source_path,
            update_mode=update_mode,
            identity_key=identity_key,
        )

        current_local_path = (
            plan.current_version.local_path if plan.current_version else None
        )
        if (
            plan.update_mode is UpdateMode.SNAPSHOT
            and current_local_path is not None
            and Path(current_local_path).exists()
        ):
            return self._record_hit(plan)

        read_result = self._client.read(
            source_url=plan.source_url,
            request_headers=dict(plan.request_headers),
            temp_path=plan.temp_path,
        )
        if (
            read_result.outcome is ReadOutcome.NOT_MODIFIED
            and current_local_path is not None
            and Path(current_local_path).exists()
        ):
            return self._record_hit(plan, read_result=read_result)

        if read_result.outcome is ReadOutcome.NOT_MODIFIED:
            logger.info(
                "cached file missing after not-modified response; re-reading source_url=%s",
                plan.source_url,
            )
            read_result = self._client.read(
                source_url=plan.source_url,
                request_headers={},
                temp_path=plan.temp_path,
            )

        if read_result.outcome is not ReadOutcome.DOWNLOADED:
            raise RuntimeError("client returned unexpected outcome without download")
        if read_result.temp_path is None or read_result.sha256 is None:
            raise RuntimeError(
                "downloaded client result must include temp_path and sha256"
            )

        return self._record_store(plan, read_result)

    def get_many(
        self,
        objects: Iterable[RawObjectRequest],
        *,
        changed_only: bool = True,
        unpublished_only: bool = False,
    ) -> list[RawObjectResult]:
        results: list[RawObjectResult] = []
        for object_request in objects:
            result = self.get(
                source_name=object_request.source_name,
                dataset_name=object_request.dataset_name,
                source_url=object_request.source_url,
                source_path=object_request.source_path,
                update_mode=object_request.update_mode,
                identity_key=object_request.identity_key,
            )
            if changed_only and not result.changed:
                continue
            if unpublished_only and self.is_published(result):
                continue
            results.append(result)
        return results

    def get_all(self, objects: Iterable[RawObjectRequest]) -> list[RawObjectResult]:
        return self.get_many(objects, changed_only=False)

    def get_changed(self, objects: Iterable[RawObjectRequest]) -> list[RawObjectResult]:
        return self.get_many(objects)

    def get_unpublished(
        self, objects: Iterable[RawObjectRequest]
    ) -> list[RawObjectResult]:
        return self.get_many(objects, changed_only=False, unpublished_only=True)

    def mark_published(
        self,
        result: RawObjectResult,
        *,
        publication_scope: str | None = None,
        publisher_run_id: str | None = None,
        published_at: datetime | None = None,
    ) -> None:
        with self._ledger.transaction():
            self._ledger.mark_published(
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
        results: Iterable[RawObjectResult],
        *,
        publication_scope: str | None = None,
        publisher_run_id: str | None = None,
        published_at: datetime | None = None,
    ) -> None:
        for result in results:
            self.mark_published(
                result,
                publication_scope=publication_scope,
                publisher_run_id=publisher_run_id,
                published_at=published_at,
            )

    def is_published(self, result: RawObjectResult) -> bool:
        with self._ledger.transaction():
            return self._ledger.is_published(
                source_name=result.raw_object.source_name,
                dataset_name=result.raw_object.dataset_name,
                identity_hash=result.raw_object.identity_hash,
                sha256=result.version.sha256,
            )

    def _record_hit(
        self,
        plan: _RawObjectPlan,
        *,
        read_result: ClientReadResult | None = None,
    ) -> RawObjectResult:
        checked_at = (
            read_result.fetched_at if read_result is not None else datetime.now(UTC)
        )
        with self._ledger.transaction():
            raw_object = self._ledger.touch_raw_object(
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
        return RawObjectResult(
            status=RawObjectStatus.HIT,
            raw_object=raw_object,
            version=plan.current_version,
        )

    def _record_store(
        self, plan: _RawObjectPlan, read_result: ClientReadResult
    ) -> RawObjectResult:
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
            with self._ledger.transaction():
                raw_object = self._ledger.touch_raw_object(
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
                previous_versions = self._ledger.list_versions(raw_object.id)
                self._ledger.insert_version(version)
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
            with self._ledger.transaction():
                self._ledger.delete_versions([stale.id for stale in previous_versions])
            for stale_version in previous_versions:
                if stale_version.local_path != version.local_path:
                    Path(stale_version.local_path).unlink(missing_ok=True)

        return RawObjectResult(
            status=RawObjectStatus.STORED,
            raw_object=raw_object,
            version=version,
        )


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


def _build_temp_path(*, raw_root: Path, source_name: str) -> Path:
    source_name = _validate_path_segment(source_name, field_name="source_name")
    return raw_root / source_name / ".tmp" / f"{uuid4().hex}.download"


def _build_final_path(
    *,
    raw_root: Path,
    plan: _RawObjectPlan,
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
