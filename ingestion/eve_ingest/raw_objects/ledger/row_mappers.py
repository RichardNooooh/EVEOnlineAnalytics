from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from eve_ingest.raw_objects.http_models import RevalidationMetadata
from eve_ingest.raw_objects.ledger.columns import (
    RAW_OBJECT_COLUMNS,
    RAW_OBJECT_SEEN_COLUMNS,
    RAW_OBJECT_VERSION_COLUMNS,
)
from eve_ingest.raw_objects.ledger.models import (
    PublicationContext,
    RawObjectEntry,
    RawObjectRef,
    RawObjectVersion,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from sqlalchemy.engine import RowMapping

    from eve_ingest.raw_objects.primitives import UpdateMode


def normalize_ledger_url(ledger_url: str) -> str:
    if "+psycopg" in ledger_url and "+psycopg2" not in ledger_url:
        return ledger_url
    if ledger_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + ledger_url.removeprefix("postgresql://")
    if ledger_url.startswith("postgres://"):
        return "postgresql+psycopg://" + ledger_url.removeprefix("postgres://")
    raise ValueError("ledger_url must be a PostgreSQL URL")


def require_update_mode(raw_object: RawObjectEntry | None, update_mode: UpdateMode) -> None:
    if raw_object is None or raw_object.ref.update_mode is update_mode:
        return
    raise ValueError(
        f"raw object update_mode mismatch: stored={raw_object.ref.update_mode.value} requested={update_mode.value}"
    )


def entity_to_row(
    entity: Any,
    column_map: Mapping[str, str | None],
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize a dataclass to a flat DB row dict using a column-to-field-path map.

    ``dataclasses.asdict(entity)`` renders the entity as nested dicts.
    Each entry in *column_map* navigates into that structure via dot-separated
    keys to extract the value for the corresponding SQL column.

    Example for ``RAW_OBJECT_COLUMNS``::

        entity = RawObjectEntry(
            id="abc",
            ref=RawObjectRef(source_name="everef", ...),
            revalidation=RevalidationMetadata(etag='"xyz"', ...),
        )

        ``asdict(entity)`` produces::

            {"id": "abc", "ref": {"source_name": "everef", ...},
             "revalidation": {"etag": '"xyz"', ...}, ...}

        Dot-path ``"ref.source_name"`` navigates into that dict::

            result["source_name"] = raw["ref"]["source_name"]  # "everef"

        Dot-path ``"revalidation.etag"`` navigates one level deeper::

            result["etag"] = raw["revalidation"]["etag"]  # '"xyz"'

    Columns mapped to ``None`` are skipped — use *overrides* to supply them
    from non-entity sources (e.g. synthetic UUIDs, foreign-key references).

    Args:
        entity: Any frozen dataclass (``RawObjectEntry``, ``RawObjectVersion``,
            or ``PublicationContext``).
        column_map: Mapping of ``{sql_column_name: dot_path}``. A ``None`` path
            means the column is omitted from the result.
        overrides: Optional dict of ``{sql_column_name: value}`` merged on top
            of the extracted values. Takes precedence over all column_map values.

    Returns:
        Flat dict keyed by SQL column name, ready for ``Table.insert().values()``.
    """
    raw = asdict(entity)
    result: dict[str, Any] = {}
    for col_name, field_path in column_map.items():
        if field_path is None:
            continue
        parts = field_path.split(".")
        value: Any = raw
        for part in parts:
            value = value.get(part) if isinstance(value, dict) else getattr(value, part)
        result[col_name] = value
    if overrides:
        result.update(overrides)
    return result


def raw_object_values(raw_object: RawObjectEntry) -> dict[str, Any]:
    return entity_to_row(raw_object, RAW_OBJECT_COLUMNS)


def raw_object_seen_values(raw_object: RawObjectEntry) -> dict[str, Any]:
    return entity_to_row(raw_object, RAW_OBJECT_SEEN_COLUMNS)


def raw_object_version_values(version: RawObjectVersion) -> dict[str, Any]:
    return entity_to_row(version, RAW_OBJECT_VERSION_COLUMNS)


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
    identity_key: dict[str, Any] = cast("dict[str, Any]", row["identity_key"])
    update_mode: UpdateMode = cast("UpdateMode", row["update_mode"])
    return RawObjectEntry(
        id=cast("str", row["id"]),
        ref=RawObjectRef(
            source_name=cast("str", row["source_name"]),
            dataset_name=cast("str", row["dataset_name"]),
            identity_hash=cast("str", row["identity_hash"]),
            identity_key=identity_key,
            update_mode=update_mode,
        ),
        created_at=cast("datetime", row["created_at"]),
        last_checked_at=cast("datetime | None", row["last_checked_at"]),
        revalidation=RevalidationMetadata(
            etag=cast("str | None", row["etag"]),
            last_modified=cast("str | None", row["last_modified"]),
            content_length=cast("int | None", row["content_length"]),
        ),
    )


def row_to_raw_object_version(row: RowMapping) -> RawObjectVersion:
    return RawObjectVersion(
        id=cast("str", row["id"]),
        raw_object_id=cast("str", row["raw_object_id"]),
        source_url=cast("str", row["source_url"]),
        fetched_at=cast("datetime", row["fetched_at"]),
        revalidation=RevalidationMetadata(
            etag=cast("str | None", row["etag"]),
            last_modified=cast("str | None", row["last_modified"]),
            content_length=cast("int | None", row["content_length"]),
        ),
        sha256=cast("str", row["sha256"]),
        local_path=cast("str", row["local_path"]),
        storage_encoding=cast("str", row["storage_encoding"]),
        version_number=cast("int", row["version_number"]),
    )
