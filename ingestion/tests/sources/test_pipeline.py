from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Lock, Thread
from types import SimpleNamespace

import pytest

from eve_ingest.cli.config import EverefReferencesCliConfig
from eve_ingest.ducklake.locks import DuckLakeLockToken
from eve_ingest.ducklake.raw_tables import DuckLakeWriteMetrics, DuckLakeWriterMode, RawDuckLakeTable
from eve_ingest.raw_objects import CacheObject, CacheResult, UpdateMode
from eve_ingest.raw_objects.ledger.models import CurrentRawObjectState, PublicationContext
from eve_ingest.sources.everef.fuzzwork_orders import PUBLISHER_SPEC as FUZZWORK_ORDERS_SPEC
from eve_ingest.sources.everef.market_history import PUBLISHER_SPEC as MARKET_HISTORY_SPEC
from eve_ingest.sources.everef.market_orders import PUBLISHER_SPEC as MARKET_ORDERS_SPEC
from eve_ingest.sources.everef.reference_data import PUBLISHER_SPEC as REFERENCES_SPEC
from eve_ingest.workflows.raw_file_workflow import (
    PipelineProcessResult,
    PublicationScopeLockError,
    run_pipeline,
)
from tests.sources.everef.conftest import make_cache_result, make_everef_pipeline_config


class _FakePubtrack:
    def __init__(self) -> None:
        self.calls: list[tuple[list[CacheResult], PublicationContext | None]] = []
        self.published_versions: set[tuple[str, str]] = set()

    def filter_published(self, results: list[CacheResult]) -> set[tuple[str, str]]:
        return self.published_versions

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
        self.raw_root = Path(kwargs["raw_root"])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get_many(self, objects: list[CacheObject], mode) -> list[CacheResult]:
        path = self.raw_root / "a.csv.bz2"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data")
        return [
            make_cache_result(
                str(path),
                dataset_name="market-history",
                identity_key={"source_date": "2026-01-01"},
                source_url=objects[0].source_url,
                update_mode=UpdateMode.MUTABLE,
            )
        ]

    def load_current_states_for_results(self, results: list[CacheResult]) -> dict[str, CurrentRawObjectState | None]:
        return {
            result.raw_object.ref.identity_hash: CurrentRawObjectState(
                raw_object=result.raw_object,
                current_version=result.version,
            )
            for result in results
        }


class _FakeWriter:
    def __init__(self, config, *, lock_token, declared_mode=None, dataset_name=None) -> None:
        self.config = config
        self.lock_token = lock_token
        self.declared_mode = declared_mode
        self.dataset_name = dataset_name

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeLock:
    def __init__(self, lock_domains: tuple[str, ...]) -> None:
        self.lock_domains = lock_domains

    def __enter__(self):
        return DuckLakeLockToken.unsafe_for_tests(self.lock_domains)

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_run_pipeline_logs_summary_and_day_summary(
    monkeypatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.Cache", _FakeCache)
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.DuckLakeWriter", _FakeWriter)
    monkeypatch.setattr(
        "eve_ingest.workflows.raw_file_workflow._hold_publication_domain_locks",
        lambda *, publisher_spec, catalog_url, publication_scopes, source_date, timeout_seconds: _FakeLock(
            publisher_spec.lock_domains()
        ),
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
                publisher_spec=MARKET_HISTORY_SPEC,
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


def test_run_pipeline_rejects_writer_mode_mismatch_before_marking_published(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None, delegate_write_calls=0)

    class FakeCache(_FakeCache):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            captured.pubtrack = self.pubtrack

    class FakeWriter(_FakeWriter):
        def write(self, *args, table, mode, **kwargs):
            if self.declared_mode is not None and mode != self.declared_mode:
                requested_mode = getattr(mode, "value", str(mode))
                raise ValueError(
                    "DuckLake writer mode does not match publisher declaration "
                    f"dataset={self.dataset_name or '-'} table={table.value} "
                    f"declared_mode={self.declared_mode.value} requested_mode={requested_mode}"
                )
            captured.delegate_write_calls += 1
            raise AssertionError("delegate write should not be called for a mode mismatch")

    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.Cache", FakeCache)
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.DuckLakeWriter", FakeWriter)
    monkeypatch.setattr(
        "eve_ingest.workflows.raw_file_workflow._hold_publication_domain_locks",
        lambda *, publisher_spec, catalog_url, publication_scopes, source_date, timeout_seconds: _FakeLock(
            publisher_spec.lock_domains()
        ),
    )

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [CacheObject(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]

    def process_one(result, writer) -> PipelineProcessResult:
        writer.write(
            object(),
            table=RawDuckLakeTable.MARKET_HISTORY,
            mode=DuckLakeWriterMode.REPLACE_TABLE,
        )
        return PipelineProcessResult(success=True, source_date="2026-01-01")

    with pytest.raises(
        ValueError,
        match=(
            "DuckLake writer mode does not match publisher declaration "
            "dataset=market-history table=raw_market_history "
            "declared_mode=assert_partition_coverage_insert_missing_keys requested_mode=replace_table"
        ),
    ):
        run_pipeline(
            publisher_spec=MARKET_HISTORY_SPEC,
            objects=objects,
            config=config,
            process_one=process_one,
        )

    assert captured.delegate_write_calls == 0
    assert captured.pubtrack is not None
    assert captured.pubtrack.calls == []


def test_build_publication_scope_returns_expected_scope_strings() -> None:
    assert MARKET_ORDERS_SPEC.publication_scope({"source_date": "2026-01-01"}) == (
        "raw:market_orders:source_date=2026-01-01"
    )
    assert FUZZWORK_ORDERS_SPEC.publication_scope({"source_date": "2026-01-01"}) == (
        "raw:fuzzwork_orders:source_date=2026-01-01"
    )
    assert MARKET_HISTORY_SPEC.publication_scope({"source_date": "2026-01-01"}) == (
        "raw:market_history:source_date=2026-01-01"
    )
    assert REFERENCES_SPEC.publication_scope({"source_date": "latest"}) == "raw:references:full_extract"


def test_run_pipeline_locks_per_scope_and_threads_publication_context(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(scopes=[], pubtrack=None)

    class FakeCache:
        def __init__(self, *args, **kwargs) -> None:
            self.pubtrack = _FakePubtrack()
            self.raw_root = Path(kwargs["raw_root"])
            captured.pubtrack = self.pubtrack

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get_many(self, objects: list[CacheObject], mode) -> list[CacheResult]:
            path_a = self.raw_root / "a.csv.bz2"
            path_b = self.raw_root / "b.csv.bz2"
            path_a.parent.mkdir(parents=True, exist_ok=True)
            path_a.write_text("data")
            path_b.write_text("data")
            return [
                make_cache_result(
                    str(path_a),
                    dataset_name="market-history",
                    identity_key={"source_date": "2026-01-01"},
                    update_mode=UpdateMode.MUTABLE,
                    identity_hash="hash-a",
                    raw_object_id="obj-a",
                    version_id="ver-a",
                ),
                make_cache_result(
                    str(path_b),
                    dataset_name="market-history",
                    identity_key={"source_date": "2026-01-02"},
                    update_mode=UpdateMode.MUTABLE,
                    identity_hash="hash-b",
                    raw_object_id="obj-b",
                    version_id="ver-b",
                ),
            ]

        def load_current_states_for_results(
            self, results: list[CacheResult]
        ) -> dict[str, CurrentRawObjectState | None]:
            return {
                result.raw_object.ref.identity_hash: CurrentRawObjectState(
                    raw_object=result.raw_object,
                    current_version=result.version,
                )
                for result in results
            }

    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.Cache", FakeCache)
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.DuckLakeWriter", _FakeWriter)

    def hold_scope_locks(*, publisher_spec, catalog_url, publication_scopes, source_date):
        captured.scopes.append((publisher_spec.dataset_name, publication_scopes, source_date))
        return _FakeLock(publisher_spec.lock_domains())

    monkeypatch.setattr(
        "eve_ingest.workflows.raw_file_workflow._hold_publication_domain_locks",
        lambda *, publisher_spec, catalog_url, publication_scopes, source_date, timeout_seconds: hold_scope_locks(
            publisher_spec=publisher_spec,
            catalog_url=catalog_url,
            publication_scopes=publication_scopes,
            source_date=source_date,
        ),
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
        publisher_spec=MARKET_HISTORY_SPEC,
        objects=objects,
        config=config,
        process_one=process_one,
    )

    assert exit_code == 0
    assert captured.scopes == [
        ("market-history", ("raw:market_history:source_date=2026-01-01",), "2026-01-01"),
        ("market-history", ("raw:market_history:source_date=2026-01-02",), "2026-01-02"),
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
        "eve_ingest.workflows.raw_file_workflow._hold_publication_domain_locks",
        lambda *, publisher_spec, catalog_url, publication_scopes, source_date, timeout_seconds: (_ for _ in ()).throw(
            PublicationScopeLockError("busy")
        ),
    )

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [CacheObject(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]

    def process_one(result, writer) -> PipelineProcessResult:
        captured.process_calls += 1
        return PipelineProcessResult(success=True, source_date="2026-01-01")

    with pytest.raises(PublicationScopeLockError, match="busy"):
        run_pipeline(
            publisher_spec=MARKET_HISTORY_SPEC,
            objects=objects,
            config=config,
            process_one=process_one,
        )

    assert captured.process_calls == 0
    assert captured.pubtrack is not None
    assert captured.pubtrack.calls == []


def test_run_pipeline_rechecks_publication_after_lock_and_skips(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None, process_calls=0, writer_constructed=False)

    class FakeCache:
        def __init__(self, *args, **kwargs) -> None:
            self.pubtrack = _FakePubtrack()
            self.raw_root = Path(kwargs["raw_root"])
            captured.pubtrack = self.pubtrack

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get_many(self, objects: list[CacheObject], mode) -> list[CacheResult]:
            path = self.raw_root / "a.csv.bz2"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("data")
            result = make_cache_result(
                str(path),
                dataset_name="market-history",
                identity_key={"source_date": "2026-01-01"},
                update_mode=UpdateMode.MUTABLE,
            )
            self.pubtrack.published_versions = {(result.raw_object.ref.identity_hash, result.version.sha256)}
            return [result]

        def load_current_states_for_results(self, results: list[CacheResult]):
            raise AssertionError("already-published results should be skipped before current-state lookup")

    class FakeWriter(_FakeWriter):
        def __init__(self, config, *, lock_token) -> None:
            captured.writer_constructed = True
            super().__init__(config, lock_token=lock_token)

    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.Cache", FakeCache)
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.DuckLakeWriter", FakeWriter)
    monkeypatch.setattr(
        "eve_ingest.workflows.raw_file_workflow._hold_publication_domain_locks",
        lambda *, publisher_spec, catalog_url, publication_scopes, source_date, timeout_seconds: _FakeLock(
            publisher_spec.lock_domains()
        ),
    )

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [CacheObject(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]

    def process_one(result, writer) -> PipelineProcessResult:
        captured.process_calls += 1
        return PipelineProcessResult(success=True, source_date="2026-01-01")

    assert (
        run_pipeline(publisher_spec=MARKET_HISTORY_SPEC, objects=objects, config=config, process_one=process_one) == 0
    )
    assert captured.process_calls == 0
    assert captured.writer_constructed is False
    assert captured.pubtrack is not None
    assert captured.pubtrack.calls == []


def test_run_pipeline_skips_stale_mutable_result_after_lock(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None, process_calls=0, writer_constructed=False)

    class FakeCache:
        def __init__(self, *args, **kwargs) -> None:
            self.pubtrack = _FakePubtrack()
            self.raw_root = Path(kwargs["raw_root"])
            captured.pubtrack = self.pubtrack

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get_many(self, objects: list[CacheObject], mode) -> list[CacheResult]:
            path = self.raw_root / "a.csv.bz2"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("data")
            return [
                make_cache_result(
                    str(path),
                    dataset_name="market-history",
                    identity_key={"source_date": "2026-01-01"},
                    update_mode=UpdateMode.MUTABLE,
                )
            ]

        def load_current_states_for_results(
            self, results: list[CacheResult]
        ) -> dict[str, CurrentRawObjectState | None]:
            result = results[0]
            current_version = replace(result.version, id="ver-2", sha256="def456")
            return {
                result.raw_object.ref.identity_hash: CurrentRawObjectState(
                    raw_object=result.raw_object,
                    current_version=current_version,
                )
            }

    class FakeWriter(_FakeWriter):
        def __init__(self, config, *, lock_token) -> None:
            captured.writer_constructed = True
            super().__init__(config, lock_token=lock_token)

    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.Cache", FakeCache)
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.DuckLakeWriter", FakeWriter)
    monkeypatch.setattr(
        "eve_ingest.workflows.raw_file_workflow._hold_publication_domain_locks",
        lambda *, publisher_spec, catalog_url, publication_scopes, source_date, timeout_seconds: _FakeLock(
            publisher_spec.lock_domains()
        ),
    )

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [CacheObject(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]

    def process_one(result, writer) -> PipelineProcessResult:
        captured.process_calls += 1
        return PipelineProcessResult(success=True, source_date="2026-01-01")

    assert (
        run_pipeline(publisher_spec=MARKET_HISTORY_SPEC, objects=objects, config=config, process_one=process_one) == 0
    )
    assert captured.process_calls == 0
    assert captured.writer_constructed is False
    assert captured.pubtrack is not None
    assert captured.pubtrack.calls == []


def test_run_pipeline_skips_stale_mutable_result_with_missing_file_after_lock(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None, process_calls=0, writer_constructed=False)

    class FakeCache:
        def __init__(self, *args, **kwargs) -> None:
            self.pubtrack = _FakePubtrack()
            self.raw_root = Path(kwargs["raw_root"])
            captured.pubtrack = self.pubtrack

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get_many(self, objects: list[CacheObject], mode) -> list[CacheResult]:
            path = self.raw_root / "deleted.csv.bz2"
            return [
                make_cache_result(
                    str(path),
                    dataset_name="market-history",
                    identity_key={"source_date": "2026-01-01"},
                    update_mode=UpdateMode.MUTABLE,
                )
            ]

        def load_current_states_for_results(
            self, results: list[CacheResult]
        ) -> dict[str, CurrentRawObjectState | None]:
            result = results[0]
            current_version = replace(result.version, id="ver-2", sha256="def456")
            return {
                result.raw_object.ref.identity_hash: CurrentRawObjectState(
                    raw_object=result.raw_object,
                    current_version=current_version,
                )
            }

    class FakeWriter(_FakeWriter):
        def __init__(self, config, *, lock_token) -> None:
            captured.writer_constructed = True
            super().__init__(config, lock_token=lock_token)

    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.Cache", FakeCache)
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.DuckLakeWriter", FakeWriter)
    monkeypatch.setattr(
        "eve_ingest.workflows.raw_file_workflow._hold_publication_domain_locks",
        lambda *, publisher_spec, catalog_url, publication_scopes, source_date, timeout_seconds: _FakeLock(
            publisher_spec.lock_domains()
        ),
    )

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [CacheObject(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]

    def process_one(result, writer) -> PipelineProcessResult:
        captured.process_calls += 1
        return PipelineProcessResult(success=True, source_date="2026-01-01")

    assert (
        run_pipeline(publisher_spec=MARKET_HISTORY_SPEC, objects=objects, config=config, process_one=process_one) == 0
    )
    assert captured.process_calls == 0
    assert captured.writer_constructed is False
    assert captured.pubtrack is not None
    assert captured.pubtrack.calls == []


def test_run_pipeline_skips_stale_reference_latest_result_after_lock(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None, process_calls=0, writer_constructed=False)

    class FakeCache:
        def __init__(self, *args, **kwargs) -> None:
            self.pubtrack = _FakePubtrack()
            self.raw_root = Path(kwargs["raw_root"])
            captured.pubtrack = self.pubtrack

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get_many(self, objects: list[CacheObject], mode) -> list[CacheResult]:
            path = self.raw_root / "reference-data-latest.tar.xz"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("data")
            return [
                make_cache_result(
                    str(path),
                    dataset_name="reference-data",
                    identity_key={"source_date": "latest"},
                    source_url=objects[0].source_url,
                    update_mode=UpdateMode.MUTABLE,
                )
            ]

        def load_current_states_for_results(
            self, results: list[CacheResult]
        ) -> dict[str, CurrentRawObjectState | None]:
            result = results[0]
            current_version = replace(result.version, id="ver-2", sha256="def456")
            return {
                result.raw_object.ref.identity_hash: CurrentRawObjectState(
                    raw_object=result.raw_object,
                    current_version=current_version,
                )
            }

    class FakeWriter(_FakeWriter):
        def __init__(self, config, *, lock_token) -> None:
            captured.writer_constructed = True
            super().__init__(config, lock_token=lock_token)

    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.Cache", FakeCache)
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.DuckLakeWriter", FakeWriter)
    monkeypatch.setattr(
        "eve_ingest.workflows.raw_file_workflow._hold_publication_domain_locks",
        lambda *, publisher_spec, catalog_url, publication_scopes, source_date, timeout_seconds: _FakeLock(
            publisher_spec.lock_domains()
        ),
    )

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [
        CacheObject(
            source_url="https://data.everef.net/reference-data/reference-data-latest.tar.xz",
            identity_key={"source_date": "latest"},
        )
    ]

    def process_one(result, writer) -> PipelineProcessResult:
        captured.process_calls += 1
        return PipelineProcessResult(success=True, source_date="latest")

    assert run_pipeline(publisher_spec=REFERENCES_SPEC, objects=objects, config=config, process_one=process_one) == 0
    assert captured.process_calls == 0
    assert captured.writer_constructed is False
    assert captured.pubtrack is not None
    assert captured.pubtrack.calls == []


def test_parallel_same_scope_run_pipeline_rechecks_and_skips_second(monkeypatch, tmp_path: Path) -> None:
    raw_path = tmp_path / "raw" / "a.csv.bz2"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("data")
    result = make_cache_result(
        str(raw_path),
        dataset_name="market-history",
        identity_key={"source_date": "2026-01-01"},
        update_mode=UpdateMode.MUTABLE,
    )
    selected = Barrier(2)
    publication_lock = Lock()
    pubtrack_lock = Lock()
    published_versions: set[tuple[str, str]] = set()
    pubtrack_calls: list[list[CacheResult]] = []
    process_calls = 0
    writer_constructed = 0

    class SharedPubtrack:
        def filter_published(self, results: list[CacheResult]) -> set[tuple[str, str]]:
            with pubtrack_lock:
                return set(published_versions)

        def mark_published_many(
            self,
            results: list[CacheResult],
            *,
            context: PublicationContext | None = None,
        ) -> None:
            with pubtrack_lock:
                pubtrack_calls.append(results)
                for published_result in results:
                    published_versions.add(
                        (published_result.raw_object.ref.identity_hash, published_result.version.sha256)
                    )

    class SharedCache:
        pubtrack = SharedPubtrack()

        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get_many(self, objects: list[CacheObject], mode) -> list[CacheResult]:
            selected.wait(timeout=5)
            return [result]

        def load_current_states_for_results(
            self, results: list[CacheResult]
        ) -> dict[str, CurrentRawObjectState | None]:
            return {
                selected_result.raw_object.ref.identity_hash: CurrentRawObjectState(
                    raw_object=selected_result.raw_object,
                    current_version=selected_result.version,
                )
                for selected_result in results
            }

    class SerialLock:
        def __init__(self, lock_domains: tuple[str, ...]) -> None:
            self.lock_domains = lock_domains

        def __enter__(self):
            publication_lock.acquire()
            return DuckLakeLockToken.unsafe_for_tests(self.lock_domains)

        def __exit__(self, exc_type, exc, tb) -> None:
            publication_lock.release()

    class CountingWriter(_FakeWriter):
        def __init__(self, config, *, lock_token, declared_mode=None, dataset_name=None) -> None:
            nonlocal writer_constructed
            writer_constructed += 1
            super().__init__(config, lock_token=lock_token, declared_mode=declared_mode, dataset_name=dataset_name)

    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.Cache", SharedCache)
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.DuckLakeWriter", CountingWriter)
    monkeypatch.setattr(
        "eve_ingest.workflows.raw_file_workflow._hold_publication_domain_locks",
        lambda *, publisher_spec, catalog_url, publication_scopes, source_date, timeout_seconds: SerialLock(
            publisher_spec.lock_domains()
        ),
    )

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [CacheObject(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]
    exit_codes: list[int] = []
    errors: list[BaseException] = []

    def process_one(result, writer) -> PipelineProcessResult:
        nonlocal process_calls
        process_calls += 1
        return PipelineProcessResult(success=True, source_date="2026-01-01")

    def worker() -> None:
        try:
            exit_codes.append(
                run_pipeline(
                    publisher_spec=MARKET_HISTORY_SPEC,
                    objects=objects,
                    config=config,
                    process_one=process_one,
                )
            )
        except BaseException as exc:  # pragma: no cover - surfaced through assertion below
            errors.append(exc)

    threads = [Thread(target=worker), Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert all(thread.is_alive() is False for thread in threads)
    assert sorted(exit_codes) == [0, 0]
    assert process_calls == 1
    assert writer_constructed == 1
    assert len(pubtrack_calls) == 1
