from __future__ import annotations

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


def test_normalize_source_relative_path_returns_relative_path() -> None:
    result = normalize_source_relative_path("https://data.everef.net/a/file.csv.bz2")
    assert result == "a/file.csv.bz2"


def test_normalize_source_relative_path_strips_multi_level() -> None:
    result = normalize_source_relative_path("https://data.everef.net/a/b/c.csv")
    assert result == "a/b/c.csv"


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


def test_normalize_source_relative_path_rejects_no_host() -> None:
    with pytest.raises(ValueError, match="source_url must be an https URL"):
        normalize_source_relative_path("https://")


def test_normalize_source_relative_path_rejects_query() -> None:
    with pytest.raises(ValueError, match="source_url must not include query strings or fragments"):
        normalize_source_relative_path("https://data.everef.net/a.csv?foo=1")


def test_normalize_source_relative_path_rejects_fragment() -> None:
    with pytest.raises(ValueError, match="source_url must not include query strings or fragments"):
        normalize_source_relative_path("https://data.everef.net/a.csv#section")


# ── normalize_source_path ───────────────────────────────────────────


def test_normalize_source_path_passes_through_clean_path() -> None:
    result = normalize_source_path("a/file.csv")
    assert result == "a/file.csv"


def test_normalize_source_path_normalizes_dot() -> None:
    result = normalize_source_path("./a/file.csv")
    assert result == "a/file.csv"


def test_normalize_source_path_normalizes_double_dot() -> None:
    result = normalize_source_path("vendor/../vendor/file.csv")
    assert result == "vendor/file.csv"


def test_normalize_source_path_rejects_backslash() -> None:
    with pytest.raises(ValueError, match="must use forward slash path separators"):
        normalize_source_path("a\\file.csv")


def test_normalize_source_path_rejects_absolute() -> None:
    with pytest.raises(ValueError, match="must be relative"):
        normalize_source_path("/absolute/path.csv")


def test_normalize_source_path_rejects_query() -> None:
    with pytest.raises(ValueError, match="must not include query strings or fragments"):
        normalize_source_path("a/file.csv?q=1")


def test_normalize_source_path_rejects_fragment() -> None:
    with pytest.raises(ValueError, match="must not include query strings or fragments"):
        normalize_source_path("a/file.csv#frag")


def test_normalize_source_path_rejects_empty_after_normalization() -> None:
    with pytest.raises(ValueError, match="must include a path"):
        normalize_source_path(".")


def test_normalize_source_path_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="must include a path"):
        normalize_source_path("")


def test_normalize_source_path_rejects_escape_to_parent() -> None:
    with pytest.raises(ValueError, match="must not escape source root"):
        normalize_source_path("../escape.csv")


def test_normalize_source_path_rejects_dot_dot_only() -> None:
    with pytest.raises(ValueError, match="must not escape source root"):
        normalize_source_path("..")


def test_normalize_source_path_uses_custom_field_name() -> None:
    with pytest.raises(ValueError, match="custom_field must use forward slash"):
        normalize_source_path("a\\b.csv", field_name="custom_field")


# ── validate_identity_key ───────────────────────────────────────────


def test_validate_identity_key_passes_valid() -> None:
    validate_identity_key({"a": 1, "b": "x"})


@pytest.mark.parametrize("value", ["hello", 42, 3.14, True, None])
def test_validate_identity_key_passes_scalar_types(value: IdentityScalar) -> None:
    validate_identity_key({"key": value})


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


def test_resolve_identity_key_defaults_to_source_path() -> None:
    result = resolve_identity_key(
        identity_key=None,
        source_relative_path="a/file.csv",
    )
    assert result == {"source_path": "a/file.csv"}


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


def test_resolve_identity_key_with_single_key() -> None:
    result = resolve_identity_key(
        identity_key={"id": 42},
        source_relative_path="ignored.csv",
    )
    assert result == {"id": 42}


# ── canonical_identity_json ─────────────────────────────────────────


def test_canonical_identity_json_sorts_keys() -> None:
    result = canonical_identity_json({"b": 2, "a": 1})
    assert result == '{"a":1,"b":2}'


def test_canonical_identity_json_compact_separators() -> None:
    # no spaces after colons or commas
    result = canonical_identity_json({"x": "hello", "y": 1})
    assert " " not in result


def test_canonical_identity_json_handles_none() -> None:
    result = canonical_identity_json({"a": None})
    assert result == '{"a":null}'


def test_canonical_identity_json_handles_booleans() -> None:
    result = canonical_identity_json({"a": True, "b": False})
    assert result == '{"a":true,"b":false}'


def test_canonical_identity_json_handles_float() -> None:
    result = canonical_identity_json({"pi": 3.14})
    assert result == '{"pi":3.14}'


def test_canonical_identity_json_single_key() -> None:
    result = canonical_identity_json({"source_date": "2026-01-01"})
    assert result == '{"source_date":"2026-01-01"}'


# ── hash_identity_key ───────────────────────────────────────────────


def test_hash_identity_key_is_deterministic() -> None:
    assert hash_identity_key({"a": 1}) == hash_identity_key({"a": 1})


def test_hash_identity_key_differs_for_different_content() -> None:
    assert hash_identity_key({"a": 1}) != hash_identity_key({"a": 2})


def test_hash_identity_key_is_independent_of_key_order() -> None:
    k1 = hash_identity_key({"b": 2, "a": 1})
    k2 = hash_identity_key({"a": 1, "b": 2})
    assert k1 == k2


def test_hash_identity_key_returns_hex_string() -> None:
    result = hash_identity_key({"source_date": "2026-01-01"})
    assert isinstance(result, str)
    assert len(result) == 64
    int(result, 16)  # raises if not valid hex


def test_hash_identity_key_known_input() -> None:
    # {"a":1} canonical json is '{"a":1}', sha256 of that is known
    result = hash_identity_key({"a": 1})
    expected = "4f53cda18c2baa0c0354bb5f9a3ecbe8ed2ab0b1d8f4e0c3b9f0f0f0f0f0f0f0"
    # We just verify it's a consistent sha256 hex digest — compute expected
    import hashlib

    expected_known = hashlib.sha256(b'{"a":1}').hexdigest()
    assert result == expected_known
