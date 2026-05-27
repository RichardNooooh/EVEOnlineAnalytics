"""Column-to-field-path maps for generic entity-to-row serialization.

Each map key is a SQL column name, and each value is a dot-separated path into
the dataclass fields as rendered by ``dataclasses.asdict()``.  A ``None`` value
means the column is supplied via *overrides* at call time.

See ``mappers.entity_to_row``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RAW_OBJECT_COLUMNS: Mapping[str, str] = {
    "id": "id",
    "source_name": "ref.source_name",
    "dataset_name": "ref.dataset_name",
    "identity_key": "ref.identity_key",
    "identity_hash": "ref.identity_hash",
    "update_mode": "ref.update_mode",
    "created_at": "created_at",
    "last_checked_at": "last_checked_at",
    "etag": "revalidation.etag",
    "last_modified": "revalidation.last_modified",
    "content_length": "revalidation.content_length",
}

RAW_OBJECT_SEEN_COLUMNS: Mapping[str, str] = {
    "last_checked_at": "last_checked_at",
    "etag": "revalidation.etag",
    "last_modified": "revalidation.last_modified",
    "content_length": "revalidation.content_length",
}

RAW_OBJECT_VERSION_COLUMNS: Mapping[str, str] = {
    "id": "id",
    "raw_object_id": "raw_object_id",
    "source_url": "source_url",
    "fetched_at": "fetched_at",
    "etag": "revalidation.etag",
    "last_modified": "revalidation.last_modified",
    "content_length": "revalidation.content_length",
    "sha256": "sha256",
    "local_path": "local_path",
    "storage_encoding": "storage_encoding",
}


