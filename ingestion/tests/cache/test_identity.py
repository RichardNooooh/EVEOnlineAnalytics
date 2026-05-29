from __future__ import annotations

import hashlib

import pytest

from ingest.cache.identity import (
    canonical_identity_json,
    hash_identity_key,
    normalize_source_path,
    normalize_source_relative_path,
    resolve_identity_key,
    validate_identity_key,
)
from ingest.cache.primitives import IdentityKey, IdentityScalar


# ── normalize_source_relative_path ─────────────────────────────────


@pytest.mark.parametrize(
    ("source_url", "expected"),
    [
        ("https://data.everef.net/a/file.csv.bz2", "a/file.csv.bz2"),
        ("https://data.everef.net/a/b/c.csv", "a/b/c.csv"),
    ],
)
def test_normalize_source_relative_path_returns_relative_path(source_url: str, expected: str) -> None:
    assert normalize_source_relative_path(source_url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://data.everef.net/a.csv",
        "ftp://data.everef.net/a.csv",
        "file:///tmp/a.csv",
        "https://",
    ],
)
def test_normalize_source_relative_path_rejects_non_https(url: str) -> None:
    with pytest.raises(ValueError, match="source_url must be an https URL"):
        normalize_source_relative_path(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://data.everef.net/a.csv?foo=1",
        "https://data.everef.net/a.csv#section",
    ],
)
def test_normalize_source_relative_path_rejects_query_or_fragment(url: str) -> None:
    with pytest.raises(ValueError, match="source_url must not include query strings or fragments"):
        normalize_source_relative_path(url)


# ── normalize_source_path ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("source_path", "expected"),
    [
        ("a/file.csv", "a/file.csv"),
        ("./a/file.csv", "a/file.csv"),
        ("vendor/../vendor/file.csv", "vendor/file.csv"),
    ],
)
def test_normalize_source_path_normalizes_relative_paths(source_path: str, expected: str) -> None:
    assert normalize_source_path(source_path) == expected


@pytest.mark.parametrize(
    ("source_path", "match"),
    [
        ("a\\file.csv", "must use forward slash path separators"),
        ("/absolute/path.csv", "must be relative"),
        ("a/file.csv?q=1", "must not include query strings or fragments"),
        ("a/file.csv#frag", "must not include query strings or fragments"),
        (".", "must include a path"),
        ("", "must include a path"),
        ("../escape.csv", "must not escape source root"),
        ("..", "must not escape source root"),
    ],
)
def test_normalize_source_path_rejects_invalid_paths(source_path: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        normalize_source_path(source_path)


def test_normalize_source_path_uses_custom_field_name() -> None:
    with pytest.raises(ValueError, match="custom_field must use forward slash"):
        normalize_source_path("a\\b.csv", field_name="custom_field")


# ── validate_identity_key ───────────────────────────────────────────


@pytest.mark.parametrize(
    "identity_key",
    [
        {"a": 1, "b": "x"},
        {"key": "hello"},
        {"key": 42},
        {"key": 3.14},
        {"key": True},
        {"key": None},
    ],
)
def test_validate_identity_key_passes_valid(identity_key: dict[str, IdentityScalar]) -> None:
    validate_identity_key(identity_key)


def test_validate_identity_key_rejects_empty() -> None:
    with pytest.raises(ValueError, match="identity_key must not be empty"):
        validate_identity_key({})


def test_validate_identity_key_rejects_non_string_key() -> None:
    with pytest.raises(ValueError, match="identity_key keys must be non-empty strings"):
        validate_identity_key({1: "value"})  # type: ignore[dict-item]


def test_validate_identity_key_rejects_empty_string_key() -> None:
    with pytest.raises(ValueError, match="identity_key keys must be non-empty strings"):
        validate_identity_key({"": "value"})


def test_validate_identity_key_rejects_list_value() -> None:
    with pytest.raises(ValueError, match="identity_key values must be JSON scalar types"):
        validate_identity_key({"key": [1, 2, 3]})  # type: ignore[dict-item]


def test_validate_identity_key_rejects_dict_value() -> None:
    with pytest.raises(ValueError, match="identity_key values must be JSON scalar types"):
        validate_identity_key({"key": {"nested": 1}})  # type: ignore[dict-item]


# ── resolve_identity_key ────────────────────────────────────────────


def test_resolve_identity_key_raises_on_none() -> None:
    with pytest.raises(ValueError, match="identity_key is required"):
        resolve_identity_key(
            identity_key=None,
            source_relative_path="a/file.csv",
        )


def test_resolve_identity_key_returns_copy_of_explicit_key() -> None:
    key: IdentityKey = {"date": "2026-01-01", "type": "history"}
    result = resolve_identity_key(
        identity_key=key,
        source_relative_path="ignored.csv",
    )
    assert result == {"date": "2026-01-01", "type": "history"}
    assert result is not key


def test_resolve_identity_key_validates_explicit_key() -> None:
    with pytest.raises(ValueError, match="identity_key must not be empty"):
        resolve_identity_key(
            identity_key={},
            source_relative_path="a.csv",
        )


# ── canonical_identity_json ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("identity_key", "expected"),
    [
        ({"b": 2, "a": 1}, '{"a":1,"b":2}'),
        ({"a": None}, '{"a":null}'),
        ({"a": True, "b": False}, '{"a":true,"b":false}'),
        ({"pi": 3.14}, '{"pi":3.14}'),
        ({"source_date": "2026-01-01"}, '{"source_date":"2026-01-01"}'),
    ],
)
def test_canonical_identity_json(identity_key: IdentityKey, expected: str) -> None:
    assert canonical_identity_json(identity_key) == expected


# ── hash_identity_key ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("identity_key", "expected"),
    [
        ({"a": 1}, hashlib.sha256(b'{"a":1}').hexdigest()),
        ({"b": 2, "a": 1}, hashlib.sha256(b'{"a":1,"b":2}').hexdigest()),
    ],
)
def test_hash_identity_key(identity_key: IdentityKey, expected: str) -> None:
    assert hash_identity_key(identity_key) == expected
