"""Tests for runner helper functions."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, create_autospec

from eve_ingest.publication.results import PublishResult
from eve_ingest.publication.runner import (
    PipelineRunState,
    _filter_scope_results_after_lock,
    _group_by_publication_scope,
    _publish_per_object,
    _publish_snapshot_scope_batch,
    _record_success,
    _source_date_for_scope,
)
from eve_ingest.publication.specs import DatasetPublisherSpec
from eve_ingest.raw_objects import AcquiredRawObject


def _make_raw_object(**overrides: object) -> AcquiredRawObject:
    raw = create_autospec(AcquiredRawObject, instance=True)
    raw.identity_key = cast("dict[str, str]", overrides.get("identity_key", {"source_date": "2026-01-01"}))
    return cast("AcquiredRawObject", raw)


class TestGroupByPublicationScope:
    def test_groups_by_scope_and_returns_sorted(self) -> None:
        spec = create_autospec(DatasetPublisherSpec, instance=True)
        spec.scope_for.side_effect = lambda ik: {1: "b", 2: "a", 3: "a"}[ik.get("id", 0)]

        o1 = _make_raw_object(identity_key={"id": 1})
        o2 = _make_raw_object(identity_key={"id": 2})
        o3 = _make_raw_object(identity_key={"id": 3})

        result = _group_by_publication_scope(spec, [o1, o2, o3])

        assert list(result.keys()) == ["a", "b"]
        assert result["a"] == [o2, o3]
        assert result["b"] == [o1]
        assert spec.scope_for.call_count == 3


class TestSourceDateForScope:
    def test_extracts_source_date_from_scope(self) -> None:
        result = _source_date_for_scope("raw:test:source_date=2026-01-01", [])
        assert result == "2026-01-01"

    def test_extracts_multidigit_source_date(self) -> None:
        result = _source_date_for_scope("raw:test:source_date=2026-12-31", [])
        assert result == "2026-12-31"

    def test_falls_back_to_identity_key_when_no_source_date_in_scope(self) -> None:
        results = [_make_raw_object(identity_key={"source_date": "2026-03-15"})]
        result = _source_date_for_scope("raw:test:no_date", results)
        assert result == "2026-03-15"

    def test_returns_none_when_no_source_date_in_scope_and_no_results(self) -> None:
        result = _source_date_for_scope("raw:test:no_date", [])
        assert result is None

    def test_returns_none_when_identity_key_lacks_source_date(self) -> None:
        results = [_make_raw_object(identity_key={"other": "val"})]
        result = _source_date_for_scope("raw:test:no_date", results)
        assert result is None


class TestFilterScopeResultsAfterLock:
    def test_filters_unpublished_and_current_versions(self) -> None:
        o1 = _make_raw_object()
        o2 = _make_raw_object()
        o3 = _make_raw_object()
        scope_results = [o1, o2, o3]

        store = MagicMock()
        pubtrack = MagicMock()
        spec = create_autospec(DatasetPublisherSpec, instance=True)

        pubtrack.filter_unpublished.return_value = [o1, o2]  # o3 already published
        store.filter_current_versions.return_value = ([o1], 1, 0)  # o2 stale
        spec.dataset_name = "test"

        result = _filter_scope_results_after_lock(
            scope_results=scope_results,
            store=store,
            pubtrack=pubtrack,
            spec=spec,
            publication_scope="raw:test:source_date=2026-01-01",
        )

        assert result == [o1]


class TestPublishSnapshotScopeBatch:
    def test_all_objects_succeed_returns_list(self) -> None:
        o1 = _make_raw_object()
        o2 = _make_raw_object()
        ctx = MagicMock()
        run_state = PipelineRunState()
        publish_one = MagicMock(
            side_effect=[PublishResult(success=True, source_date="d1"), PublishResult(success=True, source_date="d2")]
        )

        result = _publish_snapshot_scope_batch(
            scope_results=[o1, o2],
            ctx=ctx,
            publish_one=publish_one,
            run_state=run_state,
        )

        assert result == [o1, o2]
        assert run_state.success == 2
        assert run_state.failed == 0
        assert run_state.per_day_success["d1"] == 1
        assert run_state.per_day_success["d2"] == 1

    def test_exception_causes_full_rollback(self) -> None:
        o1 = _make_raw_object()
        o2 = _make_raw_object()
        ctx = MagicMock()
        run_state = PipelineRunState()
        publish_one = MagicMock(side_effect=ValueError("boom"))

        result = _publish_snapshot_scope_batch(
            scope_results=[o1, o2],
            ctx=ctx,
            publish_one=publish_one,
            run_state=run_state,
        )

        assert result == []
        assert run_state.failed == 1
        assert run_state.success == 0

    def test_exception_with_source_date_from_scope(self) -> None:
        o1 = _make_raw_object()
        ctx = MagicMock()
        ctx.publication_scope = "raw:test:source_date=2026-06-01"
        run_state = PipelineRunState()
        publish_one = MagicMock(side_effect=RuntimeError("fail"))

        result = _publish_snapshot_scope_batch(
            scope_results=[o1],
            ctx=ctx,
            publish_one=publish_one,
            run_state=run_state,
        )

        assert result == []
        assert run_state.failed == 1
        assert run_state.per_day_failed["2026-06-01"] == 1


class TestPublishPerObject:
    def test_all_succeed_returns_all(self) -> None:
        o1 = _make_raw_object()
        o2 = _make_raw_object()
        ctx = MagicMock()
        run_state = PipelineRunState()
        publish_one = MagicMock(
            side_effect=[PublishResult(success=True, source_date="d1"), PublishResult(success=True, source_date="d2")]
        )

        result = _publish_per_object(
            scope_results=[o1, o2],
            ctx=ctx,
            publish_one=publish_one,
            run_state=run_state,
        )

        assert result == [o1, o2]
        assert run_state.success == 2
        assert run_state.failed == 0

    def test_some_fail_returns_only_successful(self) -> None:
        o1 = _make_raw_object()
        o2 = _make_raw_object()
        ctx = MagicMock()
        run_state = PipelineRunState()
        publish_one = MagicMock(
            side_effect=[
                PublishResult(success=True, source_date="d1"),
                PublishResult(success=False, source_date="d2"),
            ]
        )

        result = _publish_per_object(
            scope_results=[o1, o2],
            ctx=ctx,
            publish_one=publish_one,
            run_state=run_state,
        )

        assert result == [o1]
        assert run_state.success == 1
        assert run_state.failed == 1
        assert run_state.per_day_failed["d2"] == 1

    def test_exception_caught_and_continues(self) -> None:
        o1 = _make_raw_object()
        o2 = _make_raw_object(identity_key={"source_date": "2026-01-02"})
        ctx = MagicMock()
        run_state = PipelineRunState()
        publish_one = MagicMock(side_effect=[ValueError("crash"), PublishResult(success=True, source_date="d2")])

        result = _publish_per_object(
            scope_results=[o1, o2],
            ctx=ctx,
            publish_one=publish_one,
            run_state=run_state,
        )

        assert result == [o2]
        assert run_state.success == 1
        assert run_state.failed == 1
        assert run_state.per_day_failed["2026-01-01"] == 1

    def test_falls_back_to_identity_key_when_result_source_date_is_none(self) -> None:
        run_state = PipelineRunState()
        raw_object = _make_raw_object(identity_key={"source_date": "2026-02-01"})
        result = PublishResult(success=True, source_date=None)

        _record_success(run_state, raw_object, result)

        assert run_state.per_day_success["2026-02-01"] == 1

    def test_falls_back_to_unknown_when_no_source_date_available(self) -> None:
        run_state = PipelineRunState()
        raw_object = _make_raw_object(identity_key={"other": "val"})
        result = PublishResult(success=True, source_date=None)

        _record_success(run_state, raw_object, result)

        assert run_state.per_day_success["unknown"] == 1
