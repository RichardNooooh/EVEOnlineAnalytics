from __future__ import annotations

from ingest.cache.client_types import RevalidationMetadata


def merge_revalidation(existing: RevalidationMetadata, incoming: RevalidationMetadata) -> RevalidationMetadata:
    return RevalidationMetadata(
        etag=incoming.etag if incoming.etag is not None else existing.etag,
        last_modified=(incoming.last_modified if incoming.last_modified is not None else existing.last_modified),
        content_length=(incoming.content_length if incoming.content_length is not None else existing.content_length),
    )
