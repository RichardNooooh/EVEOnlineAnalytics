from __future__ import annotations

import logging

from eve_ingest.raw_objects.ledger.models import PublicationContext
from eve_ingest.raw_objects.models import CacheResult
from eve_ingest.raw_objects.publishing import PublicationTracker

logger = logging.getLogger(__name__)


class PublicationRegistry:
    """Tracks which raw object versions have been published.

    Separates publication filtering from raw object acquisition.
    Wraps PublicationTracker for the actual ledger persistence.
    """

    def __init__(self, pubtrack: PublicationTracker) -> None:
        self._pubtrack = pubtrack

    def filter_unpublished(self, results: list[CacheResult]) -> list[CacheResult]:
        """Return only results that have no publication marker."""
        if not results:
            return []
        published = self._pubtrack.filter_published(results)
        unpublished = [
            result
            for result in results
            if (result.raw_object.ref.identity_hash, result.version.sha256) not in published
        ]
        return unpublished

    def mark_published_many(
        self,
        results: list[CacheResult],
        *,
        publication_scope: str,
        publisher_run_id: str | None = None,
    ) -> None:
        """Mark many results as published under the given scope."""
        context = PublicationContext(
            publication_scope=publication_scope,
            publisher_run_id=publisher_run_id,
        )
        self._pubtrack.mark_published_many(results, context=context)
