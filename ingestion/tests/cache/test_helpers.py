from __future__ import annotations

import pytest

from ingest.cache.client_types import RevalidationMetadata
from ingest.cache.helpers import merge_revalidation


class TestMergeRevalidation:
    @pytest.mark.parametrize(
        ("existing", "incoming", "expected"),
        [
            (
                RevalidationMetadata(
                    etag='"old"',
                    last_modified="Mon, 01 Jan 2024 12:00:00 GMT",
                    content_length=50,
                ),
                RevalidationMetadata(
                    etag='"new"',
                    last_modified="Tue, 02 Jan 2024 12:00:00 GMT",
                    content_length=200,
                ),
                RevalidationMetadata(
                    etag='"new"',
                    last_modified="Tue, 02 Jan 2024 12:00:00 GMT",
                    content_length=200,
                ),
            ),
            (
                RevalidationMetadata(
                    etag='"e1"',
                    last_modified="Mon, 01 Jan 2024 12:00:00 GMT",
                    content_length=100,
                ),
                RevalidationMetadata(),
                RevalidationMetadata(
                    etag='"e1"',
                    last_modified="Mon, 01 Jan 2024 12:00:00 GMT",
                    content_length=100,
                ),
            ),
            (
                RevalidationMetadata(
                    etag='"e1"',
                    last_modified="Mon, 01 Jan 2024 12:00:00 GMT",
                    content_length=100,
                ),
                RevalidationMetadata(etag='"e2"', last_modified=None, content_length=None),
                RevalidationMetadata(
                    etag='"e2"',
                    last_modified="Mon, 01 Jan 2024 12:00:00 GMT",
                    content_length=100,
                ),
            ),
            (
                RevalidationMetadata(),
                RevalidationMetadata(
                    etag='"e1"',
                    last_modified="Mon, 01 Jan 2024 12:00:00 GMT",
                    content_length=100,
                ),
                RevalidationMetadata(
                    etag='"e1"',
                    last_modified="Mon, 01 Jan 2024 12:00:00 GMT",
                    content_length=100,
                ),
            ),
            (
                RevalidationMetadata(),
                RevalidationMetadata(),
                RevalidationMetadata(),
            ),
        ],
    )
    def test_merge_revalidation(
        self, existing: RevalidationMetadata, incoming: RevalidationMetadata, expected: RevalidationMetadata
    ) -> None:
        assert merge_revalidation(existing, incoming) == expected
