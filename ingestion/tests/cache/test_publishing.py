from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ingest.cache.client_types import RevalidationMetadata
from ingest.cache.ledger.types import PublicationContext, RawObjectEntry, RawObjectRef, RawObjectVersion
from ingest.cache.models import CacheResult, CacheResultStatus
from ingest.cache.primitives import UpdateMode
from ingest.cache.publishing import PublicationTracker
from tests.cache.fakes import InMemoryRawObjectLedger


def _ref(
    source_name: str = "everef",
    dataset_name: str = "market-orders",
    identity_hash: str = "hash-1",
    update_mode: UpdateMode = UpdateMode.SNAPSHOT,
) -> RawObjectRef:
    return RawObjectRef(
        source_name=source_name,
        dataset_name=dataset_name,
        identity_hash=identity_hash,
        identity_key={"source_path": "market-orders/history/2026/2026-01-01/file.csv.bz2"},
        update_mode=update_mode,
    )


def _result(
    source_name: str = "everef",
    dataset_name: str = "market-orders",
    identity_hash: str = "hash-1",
    sha256: str = "abc123",
    version_id: str = "v-1",
    update_mode: UpdateMode = UpdateMode.SNAPSHOT,
) -> CacheResult:
    ref = _ref(
        source_name=source_name,
        dataset_name=dataset_name,
        identity_hash=identity_hash,
        update_mode=update_mode,
    )
    return CacheResult(
        status=CacheResultStatus.STORED,
        raw_object=RawObjectEntry(
            id="obj-1",
            ref=ref,
            created_at=datetime.now(UTC),
        ),
        version=RawObjectVersion(
            id=version_id,
            raw_object_id="obj-1",
            source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/file.csv.bz2",
            fetched_at=datetime.now(UTC),
            revalidation=RevalidationMetadata(),
            sha256=sha256,
            local_path="/tmp/raw/file.csv.bz2",
            storage_encoding="bz2",
            version_number=0,
        ),
    )


class TestLifecycle:
    def test_context_manager_sets_active_flag(self):
        tracker = PublicationTracker(InMemoryRawObjectLedger())
        assert not tracker._active

        with tracker:
            assert tracker._active

        assert not tracker._active

    def test_mark_published_raises_outside_context(self):
        tracker = PublicationTracker(InMemoryRawObjectLedger())
        with pytest.raises(RuntimeError, match="must be used within its owning Cache context"):
            tracker.mark_published(_result())

    def test_mark_published_many_raises_outside_context(self):
        tracker = PublicationTracker(InMemoryRawObjectLedger())
        with pytest.raises(RuntimeError, match="must be used within its owning Cache context"):
            tracker.mark_published_many([])

    def test_is_published_raises_outside_context(self):
        tracker = PublicationTracker(InMemoryRawObjectLedger())
        with pytest.raises(RuntimeError, match="must be used within its owning Cache context"):
            tracker.is_published(_result())

    def test_filter_published_raises_outside_context(self):
        tracker = PublicationTracker(InMemoryRawObjectLedger())
        with pytest.raises(RuntimeError, match="must be used within its owning Cache context"):
            tracker.filter_published([])


class TestMarkAndCheck:
    def test_is_published_returns_false_before_marking(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            assert not tracker.is_published(_result())

    def test_mark_published_then_is_published_returns_true(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            result = _result()
            tracker.mark_published(result)
            assert tracker.is_published(result)

    def test_mark_published_is_idempotent(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            result = _result()
            tracker.mark_published(result)
            tracker.mark_published(result)
            assert tracker.is_published(result)

    def test_mark_published_with_custom_context(self):
        ctx = PublicationContext(publication_scope="raw-market-history", publisher_run_id="run-1")
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            tracker.mark_published(_result(), context=ctx)
            assert tracker.is_published(_result())

    def test_mark_published_distinct_results_independent(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            result_a = _result(identity_hash="hash-a", sha256="sha-a")
            result_b = _result(identity_hash="hash-b", sha256="sha-b")
            tracker.mark_published(result_a)
            assert tracker.is_published(result_a)
            assert not tracker.is_published(result_b)

    def test_is_published_crosses_source_dataset_boundaries(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            r1 = _result(source_name="everef", dataset_name="market-orders", identity_hash="h1", sha256="s1")
            r2 = _result(source_name="everef", dataset_name="market-history", identity_hash="h1", sha256="s1")
            tracker.mark_published(r1)
            assert tracker.is_published(r1)
            assert not tracker.is_published(r2)


class TestMarkMany:
    def test_mark_published_many_marks_all(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            results = [
                _result(identity_hash="hash-a", sha256="sha-a"),
                _result(identity_hash="hash-b", sha256="sha-b"),
            ]
            tracker.mark_published_many(results)
            assert tracker.is_published(results[0])
            assert tracker.is_published(results[1])

    def test_mark_published_many_empty(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            tracker.mark_published_many([])

    def test_mark_published_many_with_context(self):
        ctx = PublicationContext(publication_scope="raw-market-orders")
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            results = [
                _result(identity_hash="hash-a", sha256="sha-a"),
                _result(identity_hash="hash-b", sha256="sha-b"),
            ]
            tracker.mark_published_many(results, context=ctx)
            assert tracker.is_published(results[0])
            assert tracker.is_published(results[1])

    def test_mark_published_many_different_source_dataset_groups(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            results = [
                _result(source_name="everef", dataset_name="market-orders", identity_hash="h1", sha256="s1"),
                _result(source_name="everef", dataset_name="market-history", identity_hash="h2", sha256="s2"),
                _result(source_name="other", dataset_name="test", identity_hash="h3", sha256="s3"),
            ]
            tracker.mark_published_many(results)
            for r in results:
                assert tracker.is_published(r)


class TestFilterPublished:
    def test_filter_published_none_published_returns_empty(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            results = [
                _result(identity_hash="hash-a", sha256="sha-a"),
                _result(identity_hash="hash-b", sha256="sha-b"),
            ]
            assert tracker.filter_published(results) == set()

    def test_filter_published_all_published_returns_all(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            results = [
                _result(identity_hash="hash-a", sha256="sha-a"),
                _result(identity_hash="hash-b", sha256="sha-b"),
            ]
            tracker.mark_published_many(results)
            assert tracker.filter_published(results) == {("hash-a", "sha-a"), ("hash-b", "sha-b")}

    def test_filter_published_subset(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            result_a = _result(identity_hash="hash-a", sha256="sha-a")
            result_b = _result(identity_hash="hash-b", sha256="sha-b")
            result_c = _result(identity_hash="hash-c", sha256="sha-c")
            tracker.mark_published(result_a)
            tracker.mark_published(result_c)
            published = tracker.filter_published([result_a, result_b, result_c])
            assert published == {("hash-a", "sha-a"), ("hash-c", "sha-c")}

    def test_filter_published_empty_input(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            assert tracker.filter_published([]) == set()

    def test_filter_published_calls_per_group_key(self):
        ledger = InMemoryRawObjectLedger()
        with PublicationTracker(ledger) as tracker:
            group_a = [
                _result(source_name="everef", dataset_name="market-orders", identity_hash=f"h{i}", sha256=f"s{i}")
                for i in range(3)
            ]
            group_b = [
                _result(source_name="other", dataset_name="data", identity_hash=f"h{i}", sha256=f"s{i}")
                for i in range(3)
            ]
            tracker.mark_published_many(group_a + group_b)
            tracker.filter_published(group_a + group_b)
            assert ledger.filter_published_calls == 2

    def test_filter_published_deduplicates_duplicate_input(self):
        with PublicationTracker(InMemoryRawObjectLedger()) as tracker:
            result = _result(identity_hash="hash-a", sha256="sha-a")
            tracker.mark_published(result)
            published = tracker.filter_published([result, result, result])
            assert published == {("hash-a", "sha-a")}
