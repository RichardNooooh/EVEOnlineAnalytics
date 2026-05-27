from __future__ import annotations

import pytest

from ingest.cache.client_types import RevalidationMetadata
from ingest.cache.helpers import merge_revalidation


class TestMergeRevalidation:
    def test_all_incoming_fields_override_existing(self) -> None:
        existing = RevalidationMetadata(
            etag='"old"',
            last_modified="Mon, 01 Jan 2024 12:00:00 GMT",
            content_length=50,
        )
        incoming = RevalidationMetadata(
            etag='"new"',
            last_modified="Tue, 02 Jan 2024 12:00:00 GMT",
            content_length=200,
        )
        result = merge_revalidation(existing, incoming)
        assert result.etag == '"new"'
        assert result.last_modified == "Tue, 02 Jan 2024 12:00:00 GMT"
        assert result.content_length == 200

    def test_incoming_none_uses_existing(self) -> None:
        existing = RevalidationMetadata(
            etag='"e1"',
            last_modified="Mon, 01 Jan 2024 12:00:00 GMT",
            content_length=100,
        )
        incoming = RevalidationMetadata()
        result = merge_revalidation(existing, incoming)
        assert result.etag == '"e1"'
        assert result.last_modified == "Mon, 01 Jan 2024 12:00:00 GMT"
        assert result.content_length == 100

    def test_incoming_partial_merge(self) -> None:
        existing = RevalidationMetadata(
            etag='"e1"',
            last_modified="Mon, 01 Jan 2024 12:00:00 GMT",
            content_length=100,
        )
        incoming = RevalidationMetadata(etag='"e2"', last_modified=None, content_length=None)
        result = merge_revalidation(existing, incoming)
        assert result.etag == '"e2"'
        assert result.last_modified == "Mon, 01 Jan 2024 12:00:00 GMT"
        assert result.content_length == 100

    def test_incoming_partial_merge_other_fields(self) -> None:
        existing = RevalidationMetadata(
            etag='"e1"',
            last_modified="Mon, 01 Jan 2024 12:00:00 GMT",
            content_length=100,
        )
        incoming = RevalidationMetadata(etag=None, last_modified="Tue, 02 Jan 2024 12:00:00 GMT", content_length=200)
        result = merge_revalidation(existing, incoming)
        assert result.etag == '"e1"'
        assert result.last_modified == "Tue, 02 Jan 2024 12:00:00 GMT"
        assert result.content_length == 200

    def test_both_all_none_produces_all_none(self) -> None:
        existing = RevalidationMetadata()
        incoming = RevalidationMetadata()
        result = merge_revalidation(existing, incoming)
        assert result.etag is None
        assert result.last_modified is None
        assert result.content_length is None

    def test_existing_none_incoming_full(self) -> None:
        existing = RevalidationMetadata()
        incoming = RevalidationMetadata(
            etag='"e1"',
            last_modified="Mon, 01 Jan 2024 12:00:00 GMT",
            content_length=100,
        )
        result = merge_revalidation(existing, incoming)
        assert result.etag == '"e1"'
        assert result.last_modified == "Mon, 01 Jan 2024 12:00:00 GMT"
        assert result.content_length == 100

    def test_returns_new_instance(self) -> None:
        existing = RevalidationMetadata(etag='"e1"', last_modified="Mon, 01 Jan 2024 12:00:00 GMT", content_length=100)
        incoming = RevalidationMetadata(etag='"e2"')
        result = merge_revalidation(existing, incoming)
        assert result is not existing
        assert result is not incoming

    @pytest.mark.parametrize(
        ("existing", "incoming", "expected_etag", "expected_lm", "expected_cl"),
        [
            (
                RevalidationMetadata(etag='"a"', last_modified="LM-A", content_length=1),
                RevalidationMetadata(etag='"b"', last_modified="LM-B", content_length=2),
                '"b"',
                "LM-B",
                2,
            ),
            (
                RevalidationMetadata(etag=None, last_modified=None, content_length=None),
                RevalidationMetadata(etag='"b"', last_modified="LM-B", content_length=2),
                '"b"',
                "LM-B",
                2,
            ),
            (
                RevalidationMetadata(etag='"a"', last_modified="LM-A", content_length=1),
                RevalidationMetadata(etag=None, last_modified=None, content_length=None),
                '"a"',
                "LM-A",
                1,
            ),
        ],
    )
    def test_parametrized_combinations(
        self,
        existing: RevalidationMetadata,
        incoming: RevalidationMetadata,
        expected_etag: str | None,
        expected_lm: str | None,
        expected_cl: int | None,
    ) -> None:
        result = merge_revalidation(existing, incoming)
        assert result.etag == expected_etag
        assert result.last_modified == expected_lm
        assert result.content_length == expected_cl
