from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from eve_ingest.cli.config import EverefReferencesCliConfig
from eve_ingest.ducklake.raw_tables import DuckLakeWriteMetrics, DuckLakeWriterMode, RawDuckLakeTable
from eve_ingest.raw_objects import CacheObject, CacheResult, UpdateMode
from eve_ingest.raw_objects.ledger.models import PublicationContext
from eve_ingest.workflows.raw_file_workflow import (
    PipelineProcessResult,
    PublicationScopeLockError,
    _build_publication_scope,
    run_pipeline,
)
from tests.sources.everef.conftest import make_cache_result, make_everef_pipeline_config


class _FakePubtrack:
    def __init__(self) -> None:
        self.calls: list[tuple[list[CacheResult], PublicationContext | None]] = []

    def mark_published_many(
        self,
        results: list[CacheResult],
        *,
        context: PublicationContext | None = None,
    ) -> None:
        self.calls.append((results, context))


class _FakeCache:
    def __init__(self, *args, **kwargs) -> None:
        self.pubtrack = _FakePubtrack()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get_many(self, objects: list[CacheObject], mode) -> list[CacheResult]:
        return [
            make_cache_result(
                "/tmp/a.csv.bz2",
                dataset_name="market-history",
                identity_key={"source_date": "2026-01-01"},
                source_url=objects[0].source_url,
            )
        ]


class _FakeWriter:
    def __init__(self, config) -> None:
        self.config = config

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_run_pipeline_logs_summary_and_day_summary(
    monkeypatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.Cache", _FakeCache)
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.DuckLakeWriter", _FakeWriter)
    monkeypatch.setattr(
        "eve_ingest.workflows.raw_file_workflow._hold_publication_scope_locks",
        lambda *, catalog_url, publication_scopes: _FakeLock(),
    )
    pipeline_logger = logging.getLogger("eve_ingest.workflows.raw_file_workflow")

    config = make_everef_pipeline_config(
        EverefReferencesCliConfig,
        tmp_path,
    )
    objects = [
        CacheObject(
            source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
            identity_key={"source_date": "2026-01-01"},
        )
    ]

    def process_one(result, writer) -> PipelineProcessResult:
        return PipelineProcessResult(
            success=True,
            source_date="2026-01-01",
            write_metrics=(
                DuckLakeWriteMetrics(
                    table=RawDuckLakeTable.MARKET_HISTORY,
                    mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
                    attempted_rows=10,
                    inserted_rows=7,
                    matched_rows=3,
                    replaced_rows=0,
                ),
            ),
        )

    pipeline_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="eve_ingest.workflows.raw_file_workflow"):
            exit_code = run_pipeline(
                dataset_name="market-history",
                update_mode=UpdateMode.MUTABLE,
                objects=objects,
                config=config,
                process_one=process_one,
            )
    finally:
        pipeline_logger.removeHandler(caplog.handler)

    assert exit_code == 0
    assert (
        "Pipeline summary dataset=market-history requested_objects=1 processable_objects=1 success=1 failed=0 marked_published=1 exit_code=0"
        in caplog.text
    )
    assert (
        "Pipeline day summary dataset=market-history source_date=2026-01-01 requested_objects=1 processable_objects=1 success=1 failed=0 attempted_rows=10 inserted_rows=7 matched_rows=3 replaced_rows=0"
        in caplog.text
    )


def test_build_publication_scope_returns_expected_scope_strings() -> None:
    assert _build_publication_scope(dataset_name="market-orders", identity_key={"source_date": "2026-01-01"}) == (
        "raw:market_orders:source_date=2026-01-01"
    )
    assert (
        _build_publication_scope(
            dataset_name="fuzzwork-orders",
            identity_key={"source_date": "2026-01-01"},
        )
        == "raw:fuzzwork_orders:source_date=2026-01-01"
    )
    assert _build_publication_scope(dataset_name="market-history", identity_key={"source_date": "2026-01-01"}) == (
        "raw:market_history:source_date=2026-01-01"
    )
    assert _build_publication_scope(dataset_name="reference-data", identity_key={"source_date": "latest"}) == (
        "raw:references:full_extract"
    )


def test_run_pipeline_locks_per_scope_and_threads_publication_context(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(scopes=[], pubtrack=None)

    class FakeCache:
        def __init__(self, *args, **kwargs) -> None:
            self.pubtrack = _FakePubtrack()
            captured.pubtrack = self.pubtrack

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get_many(self, objects: list[CacheObject], mode) -> list[CacheResult]:
            return [
                make_cache_result(
                    "/tmp/a.csv.bz2",
                    dataset_name="market-history",
                    identity_key={"source_date": "2026-01-01"},
                ),
                make_cache_result(
                    "/tmp/b.csv.bz2",
                    dataset_name="market-history",
                    identity_key={"source_date": "2026-01-02"},
                ),
            ]

    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.Cache", FakeCache)
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.DuckLakeWriter", _FakeWriter)

    def hold_scope_locks(*, catalog_url, publication_scopes):
        captured.scopes.append(publication_scopes)
        return _FakeLock()

    monkeypatch.setattr(
        "eve_ingest.workflows.raw_file_workflow._hold_publication_scope_locks",
        hold_scope_locks,
    )
    monkeypatch.setenv("AIRFLOW_CTX_RUN_ID", "airflow-run-123")

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [
        CacheObject(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"}),
        CacheObject(source_url="https://example.com/b.csv.bz2", identity_key={"source_date": "2026-01-02"}),
    ]

    def process_one(result, writer) -> PipelineProcessResult:
        return PipelineProcessResult(success=True, source_date=str(result.identity_key["source_date"]))

    exit_code = run_pipeline(
        dataset_name="market-history",
        update_mode=UpdateMode.MUTABLE,
        objects=objects,
        config=config,
        process_one=process_one,
    )

    assert exit_code == 0
    assert captured.scopes == [
        ("raw:market_history:source_date=2026-01-01",),
        ("raw:market_history:source_date=2026-01-02",),
    ]
    assert captured.pubtrack is not None
    assert len(captured.pubtrack.calls) == 2
    contexts = [context for _, context in captured.pubtrack.calls]
    assert [context.publication_scope for context in contexts] == [
        "raw:market_history:source_date=2026-01-01",
        "raw:market_history:source_date=2026-01-02",
    ]
    assert all(context.publisher_run_id == "airflow-run-123" for context in contexts)


def test_run_pipeline_fails_whole_run_on_publication_lock_contention(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None, process_calls=0)

    class FakeCache:
        def __init__(self, *args, **kwargs) -> None:
            self.pubtrack = _FakePubtrack()
            captured.pubtrack = self.pubtrack

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get_many(self, objects: list[CacheObject], mode) -> list[CacheResult]:
            return [
                make_cache_result(
                    "/tmp/a.csv.bz2",
                    dataset_name="market-history",
                    identity_key={"source_date": "2026-01-01"},
                )
            ]

    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.Cache", FakeCache)
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.DuckLakeWriter", _FakeWriter)
    monkeypatch.setattr(
        "eve_ingest.workflows.raw_file_workflow._hold_publication_scope_locks",
        lambda *, catalog_url, publication_scopes: (_ for _ in ()).throw(PublicationScopeLockError("busy")),
    )

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [CacheObject(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]

    def process_one(result, writer) -> PipelineProcessResult:
        captured.process_calls += 1
        return PipelineProcessResult(success=True, source_date="2026-01-01")

    with pytest.raises(PublicationScopeLockError, match="busy"):
        run_pipeline(
            dataset_name="market-history",
            update_mode=UpdateMode.MUTABLE,
            objects=objects,
            config=config,
            process_one=process_one,
        )

    assert captured.process_calls == 0
    assert captured.pubtrack is not None
    assert captured.pubtrack.calls == []
