from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.engine import RowMapping

from ingest.cache.models import (
    PublicationContext,
    RawObjectRef,
    RawObjectEntry,
    RawObjectVersion,
    RevalidationMetadata,
    UpdateMode,
)


def normalize_ledger_url(ledger_url: str) -> str:
    if ledger_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + ledger_url.removeprefix("postgresql://")
    if ledger_url.startswith("postgres://"):
        return "postgresql+psycopg://" + ledger_url.removeprefix("postgres://")
    raise ValueError("ledger_url must be a PostgreSQL URL")


def require_update_mode(raw_object: RawObjectEntry | None, update_mode: UpdateMode) -> None:
    if raw_object is None or raw_object.update_mode is update_mode:
        return
    raise ValueError(
        f"raw object update_mode mismatch: stored={raw_object.update_mode.value} requested={update_mode.value}"
    )


def raw_object_values(raw_object: RawObjectEntry) -> dict[str, Any]:
    return {
        "id": raw_object.id,
        "source_name": raw_object.ref.source_name,
        "dataset_name": raw_object.ref.dataset_name,
        "identity_key": dict(raw_object.identity_key),
        "identity_hash": raw_object.ref.identity_hash,
        "update_mode": raw_object.update_mode,
        "created_at": raw_object.created_at,
        "last_checked_at": raw_object.last_checked_at,
        "etag": raw_object.revalidation.etag,
        "last_modified": raw_object.revalidation.last_modified,
        "content_length": raw_object.revalidation.content_length,
    }


def raw_object_seen_values(raw_object: RawObjectEntry) -> dict[str, Any]:
    return {
        "last_checked_at": raw_object.last_checked_at,
        "etag": raw_object.revalidation.etag,
        "last_modified": raw_object.revalidation.last_modified,
        "content_length": raw_object.revalidation.content_length,
    }


def raw_object_version_values(version: RawObjectVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "raw_object_id": version.raw_object_id,
        "source_url": version.source_url,
        "fetched_at": version.fetched_at,
        "etag": version.revalidation.etag,
        "last_modified": version.revalidation.last_modified,
        "content_length": version.revalidation.content_length,
        "sha256": version.sha256,
        "local_path": version.local_path,
        "storage_encoding": version.storage_encoding,
    }


def raw_object_publication_values(
    *,
    ref: RawObjectRef,
    sha256: str,
    version_id: str,
    context: PublicationContext,
) -> dict[str, Any]:
    return {
        "id": uuid4().hex,
        "source_name": ref.source_name,
        "dataset_name": ref.dataset_name,
        "identity_hash": ref.identity_hash,
        "sha256": sha256,
        "version_id": version_id,
        "published_at": context.published_at,
        "publication_scope": context.publication_scope,
        "publisher_run_id": context.publisher_run_id,
    }


def row_to_raw_object(row: RowMapping) -> RawObjectEntry:
    return RawObjectEntry(
        id=cast(str, row["id"]),
        ref=RawObjectRef(
            source_name=cast(str, row["source_name"]),
            dataset_name=cast(str, row["dataset_name"]),
            identity_hash=cast(str, row["identity_hash"]),
        ),
        identity_key=cast(dict[str, Any], row["identity_key"]),
        update_mode=cast(UpdateMode, row["update_mode"]),
        created_at=cast(datetime, row["created_at"]),
        last_checked_at=cast(datetime | None, row["last_checked_at"]),
        revalidation=RevalidationMetadata(
            etag=cast(str | None, row["etag"]),
            last_modified=cast(str | None, row["last_modified"]),
            content_length=cast(int | None, row["content_length"]),
        ),
    )


def row_to_raw_object_version(row: RowMapping) -> RawObjectVersion:
    return RawObjectVersion(
        id=cast(str, row["id"]),
        raw_object_id=cast(str, row["raw_object_id"]),
        source_url=cast(str, row["source_url"]),
        fetched_at=cast(datetime, row["fetched_at"]),
        revalidation=RevalidationMetadata(
            etag=cast(str | None, row["etag"]),
            last_modified=cast(str | None, row["last_modified"]),
            content_length=cast(int | None, row["content_length"]),
        ),
        sha256=cast(str, row["sha256"]),
        local_path=cast(str, row["local_path"]),
        storage_encoding=cast(str, row["storage_encoding"]),
    )
