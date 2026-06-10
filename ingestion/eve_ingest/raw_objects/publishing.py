"""Tracks which cached raw object versions have been published."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from types import TracebackType

from eve_ingest.raw_objects.ledger import RawObjectLedger
from eve_ingest.raw_objects.ledger.models import PublicationContext, RawObjectRef
from eve_ingest.raw_objects.models import CacheResult


class PublicationTracker:
    """Tracks published versions of cached raw objects.

    Must be used as a context manager. Typically accessed through
    ``RawObjectStore.pubtrack``.
    """

    def __init__(self, ledger: RawObjectLedger) -> None:
        """Create a publication tracker.

        Args:
            ledger: Open ledger connection used for persistence.  Must remain
                alive for the tracker's lifetime.
        """
        self._ledger = ledger
        self._active = False

    def __enter__(self) -> PublicationTracker:
        self._active = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._active = False

    def _assert_active(self) -> None:
        if not self._active:
            raise RuntimeError("PublicationTracker must be used within its owning context")

    def mark_published(
        self,
        result: CacheResult,
        *,
        context: PublicationContext | None = None,
    ) -> None:
        """Record that one cached version has been published.

        Publication markers are idempotent for the same source, dataset, identity, and
        checksum.

        Args:
            result: The cached version that was published.
            context: Optional publication scope and run id.  Defaults to an
                empty context with the current timestamp.

        Example:
            ```python
            cache.pubtrack.mark_published(
                result,
                context=PublicationContext(publication_scope="raw-market-history"),
            )
            ```
        """
        self._assert_active()
        ctx = context or PublicationContext()
        with self._ledger.transaction() as tx:
            tx.publications.mark_published(
                ref=result.raw_object.ref,
                sha256=result.version.sha256,
                version_id=result.version.id,
                context=ctx,
            )

    def mark_published_many(
        self,
        results: Iterable[CacheResult],
        *,
        context: PublicationContext | None = None,
    ) -> None:
        """Record that many cached versions have been published.

        Args:
            results: Cached versions that were published.
            context: Optional publication scope and run id shared across all
                results.

        Example:
            ```python
            cache.pubtrack.mark_published_many(
                results,
                context=PublicationContext(publication_scope="raw-market-orders"),
            )
            ```
        """
        self._assert_active()
        ctx = context or PublicationContext()
        grouped: dict[tuple[str, str], list[tuple[RawObjectRef, str, str, PublicationContext]]] = defaultdict(list)
        for result in results:
            grouped[(result.raw_object.ref.source_name, result.raw_object.ref.dataset_name)].append(
                (result.raw_object.ref, result.version.sha256, result.version.id, ctx)
            )
        with self._ledger.transaction() as tx:
            for group_key, pubs in grouped.items():
                tx.publications.mark_published_many(pubs)

    def is_published(self, result: CacheResult) -> bool:
        """Return whether a cached version already has a publication marker.

        Args:
            result: The cached version to check.

        Returns:
            ``True`` when a marker exists for this source, dataset, identity,
            and checksum.

        Example:
            ```python
            if not cache.pubtrack.is_published(result):
                publish(result.path)
            ```
        """
        self._assert_active()
        with self._ledger.transaction() as tx:
            return tx.publications.is_published(
                ref=result.raw_object.ref,
                sha256=result.version.sha256,
            )

    def filter_published(self, results: Iterable[CacheResult]) -> set[tuple[str, str]]:
        """Return set of ``(identity_hash, sha256)`` pairs that are published.

        Args:
            results: Cached versions to check.

        Returns:
            Subset of input pairs that have existing publication markers,
            grouped and queried in batch for efficiency.

        Example:
            ```python
            published = tracker.filter_published(results)
            unpublished = [
                r for r in results
                if (r.raw_object.ref.identity_hash, r.version.sha256) not in published
            ]
            ```
        """
        self._assert_active()
        versions_by_group: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        for result in results:
            ref = result.raw_object.ref
            versions_by_group[ref.group_key].append((ref.identity_hash, result.version.sha256))

        published: set[tuple[str, str]] = set()
        with self._ledger.transaction() as tx:
            for group_key, versions in versions_by_group.items():
                published.update(tx.publications.filter_published(group_key=group_key, versions=versions))
        return published

    def filter_unpublished(self, results: Iterable[CacheResult]) -> list[CacheResult]:
        """Return results that have no publication marker.

        Args:
            results: Cached versions to check.

        Returns:
            Input results that lack existing publication markers.
        """
        self._assert_active()
        published = self.filter_published(results)
        return [
            result
            for result in results
            if (result.raw_object.ref.identity_hash, result.version.sha256) not in published
        ]
