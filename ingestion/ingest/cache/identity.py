from __future__ import annotations

import json
import posixpath
from collections.abc import Mapping
from hashlib import sha256
from urllib.parse import urlparse

from ingest.cache.models import IdentityKey, IdentityScalar

_SCALAR_TYPES = (str, int, float, bool, type(None))


def normalize_source_relative_path(source_url: str) -> str:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source_url must be an http or https URL with a host")
    if parsed.query or parsed.fragment:
        raise ValueError("source_url must not include query strings or fragments")
    return normalize_source_path(parsed.path.lstrip("/"), field_name="source_url path")


def normalize_source_path(source_path: str, *, field_name: str = "source_path") -> str:
    if "\\" in source_path:
        raise ValueError(f"{field_name} must use forward slash path separators")
    if source_path.startswith("/"):
        raise ValueError(f"{field_name} must be relative")
    if "?" in source_path or "#" in source_path:
        raise ValueError(f"{field_name} must not include query strings or fragments")
    normalized = posixpath.normpath(source_path)
    if normalized in {"", "."}:
        raise ValueError(f"{field_name} must include a path")
    if normalized.startswith("../") or normalized == "..":
        raise ValueError(f"{field_name} must not escape source root")
    return normalized


def resolve_identity_key(
    *,
    identity_key: Mapping[str, IdentityScalar] | None,
    source_relative_path: str,
) -> dict[str, IdentityScalar]:
    if identity_key is not None:
        validate_identity_key(identity_key)
        return dict(identity_key)
    return {"source_path": source_relative_path}


def validate_identity_key(identity_key: Mapping[str, IdentityScalar]) -> None:
    if not identity_key:
        raise ValueError("identity_key must not be empty")
    for key, value in identity_key.items():
        if not isinstance(key, str) or not key:
            raise ValueError("identity_key keys must be non-empty strings")
        if not isinstance(value, _SCALAR_TYPES):
            raise ValueError("identity_key values must be JSON scalar types")


def canonical_identity_json(identity_key: IdentityKey) -> str:
    return json.dumps(
        identity_key, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def hash_identity_key(identity_key: IdentityKey) -> str:
    return sha256(canonical_identity_json(identity_key).encode("ascii")).hexdigest()
