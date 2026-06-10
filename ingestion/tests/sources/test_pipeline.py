from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Lock, Thread
from types import SimpleNamespace

import pytest

from eve_ingest.cli.config import EverefReferencesCliConfig
from eve_ingest.ducklake.locks import DuckLakeLockTimeoutError, DuckLakeLockToken
from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriteMetrics,
    DuckLakeWriterMode,
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
)
from eve_ingest.publication.context import PublishContext
from eve_ingest.publication.source_prep import SourcePreparationContext
from eve_ingest.publication.service import PublicationService
from eve_ingest.publication.errors import SnapshotScopePublishError
from eve_ingest.publication.results import PublishResult
from eve_ingest.publication.runner import run_dataset_pipeline
from eve_ingest.raw_objects import RawObjectRequest, AcquiredRawObject, UpdateMode
from eve_ingest.raw_objects.ledger.models import CurrentRawObjectState, PublicationContext
from eve_ingest.sources.everef.fuzzwork_orders import PUBLISHER_SPEC as FUZZWORK_ORDERS_SPEC
from eve_ingest.sources.everef.market_history import PUBLISHER_SPEC as MARKET_HISTORY_SPEC
from eve_ingest.sources.everef.market_orders import PUBLISHER_SPEC as MARKET_ORDERS_SPEC
from eve_ingest.sources.everef.reference_data import PUBLISHER_SPEC as REFERENCES_SPEC
from tests.sources.everef.conftest import make_cache_result, make_everef_pipeline_config


class _FakePubtrack:
    def __init__(self) -> None:
        self.calls: list[tuple[list[AcquiredRawObject], str | None, str | None]] = []
        self.published_versions: set[tuple[str, str]] = set()

    def filter_published(self, results: list[AcquiredRawObject]) -> set[tuple[str, str]]:
        return self.published_versions

    def filter_unpublished(self, results: list[AcquiredRawObject]) -> list[AcquiredRawObject]:
        published = self.filter_published(results)
        return [r for r in results if (r.raw_object.ref.identity_hash, r.version.sha256) not in published]

    def mark_published_many(
        self,
        results: list[AcquiredRawObject],
        *,
        context: PublicationContext | None = None,
    ) -> None:
        ctx = context or PublicationContext()
        self.calls.append((results, ctx.publication_scope, ctx.publisher_run_id))
        for r in results:
            self.published_versions.add((r.raw_object.ref.identity_hash, r.version.sha256))


class _FakeStore:
    def __init__(self, *args, **kwargs) -> None:
        self.pubtrack = _FakePubtrack()
        self.raw_root = Path(kwargs.get("raw_root", "/tmp"))

    def __enter__(self) -> _FakeStore:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    @property
    def ledger(self) -> object:
        return None

    def acquire_many(self, objects: list[RawObjectRequest]) -> list[AcquiredRawObject]:
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

    def load_current_states_for_results(
        self, results: list[AcquiredRawObject]
    ) -> dict[str, CurrentRawObjectState | None]:
        return {
            result.raw_object.ref.identity_hash: CurrentRawObjectState(
                raw_object=result.raw_object,
                current_version=result.version,
            )
            for result in results
        }

    def filter_current_versions(self, results: list[AcquiredRawObject]) -> tuple[list[AcquiredRawObject], int, int]:
        mutable_results = [r for r in results if r.update_mode is UpdateMode.MUTABLE]
        if not mutable_results:
            return results, 0, 0
        current_states = self.load_current_states_for_results(mutable_results)
        current_results: list[AcquiredRawObject] = []
        stale_count = 0
        missing_stale_count = 0
        for result in results:
            if result.update_mode is not UpdateMode.MUTABLE:
                current_results.append(result)
                continue
            state = current_states.get(result.raw_object.ref.identity_hash)
            is_current = (
                state is not None
                and state.current_version.id == result.version.id
                and state.current_version.sha256 == result.version.sha256
                and state.current_version.local_path == result.version.local_path
            )
            path_exists = Path(result.path).exists()
            if not is_current:
                if not path_exists:
                    missing_stale_count += 1
                else:
                    stale_count += 1
                continue
            if not path_exists:
                raise FileNotFoundError(f"Current cached raw object file is missing: {result.path}")
            current_results.append(result)
        return current_results, stale_count, missing_stale_count


class _FakeSession:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    @contextmanager
    def transaction(self):
        yield

    def quote_sql_string(self, value: str) -> str:
        return value


class _FakeRawTablePublisher:
    def __init__(self, session, *, lock_token, declared_policy=None, dataset_name=None) -> None:
        self.session = session
        self.lock_token = lock_token
        self.declared_policy = declared_policy
        self.dataset_name = dataset_name


class _FakeProvenanceRepository:
    def __init__(self, session, *, lock_token) -> None:
        self.session = session
        self.lock_token = lock_token
        self.recorded: tuple | None = None
        self.failed: tuple | None = None

    def record_source_object(self, metadata: dict, *, table) -> None:
        self.recorded = (metadata, table)

    def mark_failed(self, source_ref_id: str, *, table, reason: str) -> None:
        self.failed = (source_ref_id, reason, table)


class _FakeLock:
    def __init__(self, lock_domains: tuple[str, ...]) -> None:
        self.lock_domains = lock_domains

    def __enter__(self):
        return DuckLakeLockToken.unsafe_for_tests(self.lock_domains)

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_publish_context_fail_source_object() -> None:
    session = _FakeSession()
    provenance = _FakeProvenanceRepository(None, lock_token=None)
    raw_tables = _FakeRawTablePublisher(session, lock_token=None)
    prep_ctx = SourcePreparationContext(session=session)
    service = PublicationService(
        raw_tables=raw_tables,
        provenance=provenance,
        session=session,
        spec=MARKET_ORDERS_SPEC,
    )
    ctx = PublishContext(
        spec=MARKET_ORDERS_SPEC,
        prep_ctx=prep_ctx,
        service=service,
        publication_scope="raw:market_orders:source_date=2026-01-01",
    )
    ctx.fail_source_object(
        source_ref_id="soid-1",
        table=RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,
        reason="see log for details",
    )
    assert provenance.failed == ("soid-1", "see log for details", RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS)


def test_run_pipeline_does_not_mark_partial_snapshot_scope_published(
    monkeypatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None)

    class FakeStore(_FakeStore):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            captured.pubtrack = self.pubtrack

        def acquire_many(self, objects: list[RawObjectRequest]) -> list[AcquiredRawObject]:
            path = self.raw_root / "a.csv.bz2"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("data")
            return [
                make_cache_result(
                    str(path),
                    dataset_name="market-orders",
                    identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-00-00"},
                    source_url=objects[0].source_url,
                    update_mode=UpdateMode.SNAPSHOT,
                    identity_hash="hash-1",
                    raw_object_id="obj-1",
                    version_id="ver-1",
                ),
                make_cache_result(
                    str(path),
                    dataset_name="market-orders",
                    identity_key={"source_date": "2026-01-01", "snapshot_time": "2026-01-01_00-30-00"},
                    source_url=objects[1].source_url,
                    update_mode=UpdateMode.SNAPSHOT,
                    identity_hash="hash-2",
                    raw_object_id="obj-2",
                    version_id="ver-2",
                ),
            ]

    monkeypatch.setattr("eve_ingest.publication.runner.RawObjectStore", FakeStore)
    monkeypatch.setattr("eve_ingest.raw_objects.store.RawObjectStore", FakeStore)
    monkeypatch.setattr(
        "eve_ingest.publication.runner.hold_ducklake_lock_domains",
        lambda *, catalog_url, lock_domains, timeout_seconds, context: _FakeLock(lock_domains),
    )
    monkeypatch.setattr("eve_ingest.publication.runner.DuckLakeSession", _FakeSession)
    monkeypatch.setattr("eve_ingest.publication.runner.RawTablePublisher", _FakeRawTablePublisher)
    monkeypatch.setattr("eve_ingest.publication.runner.SourceObjectProvenanceRepository", _FakeProvenanceRepository)

    outcomes = iter(
        [
            PublishResult(success=True, source_date="2026-01-01"),
            SnapshotScopePublishError(
                source_ref_id="soid-2",
                provenance_table=MARKET_ORDERS_SPEC.provenance_tables[0],
                metadata={"source_ref_id": "soid-2"},
                source_date="2026-01-01",
            ),
        ]
    )

    def publish_one(result, ctx) -> PublishResult:
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [
        RawObjectRequest(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"}),
        RawObjectRequest(source_url="https://example.com/b.csv.bz2", identity_key={"source_date": "2026-01-01"}),
    ]

    pipeline_logger = logging.getLogger("eve_ingest.publication.runner")

    pipeline_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="eve_ingest.publication.runner"):
            exit_code = run_dataset_pipeline(
                spec=MARKET_ORDERS_SPEC,
                discover_objects=lambda config: objects,
                config=config,
                publish_one=publish_one,
            )
    finally:
        pipeline_logger.removeHandler(caplog.handler)

    assert exit_code == 1
    assert captured.pubtrack is not None
    assert len(captured.pubtrack.calls) == 0
    assert "Pipeline summary dataset=market-orders success=0 failed=1 marked_published=0" in caplog.text


def test_run_pipeline_logs_summary_and_day_summary(
    monkeypatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("eve_ingest.publication.runner.RawObjectStore", _FakeStore)
    monkeypatch.setattr("eve_ingest.raw_objects.store.RawObjectStore", _FakeStore)

    monkeypatch.setattr(
        "eve_ingest.publication.runner.hold_ducklake_lock_domains",
        lambda *, catalog_url, lock_domains, timeout_seconds, context: _FakeLock(lock_domains),
    )
    monkeypatch.setattr("eve_ingest.publication.runner.DuckLakeSession", _FakeSession)
    monkeypatch.setattr("eve_ingest.publication.runner.RawTablePublisher", _FakeRawTablePublisher)
    monkeypatch.setattr("eve_ingest.publication.runner.SourceObjectProvenanceRepository", _FakeProvenanceRepository)

    pipeline_logger = logging.getLogger("eve_ingest.publication.runner")

    config = make_everef_pipeline_config(
        EverefReferencesCliConfig,
        tmp_path,
    )
    objects = [
        RawObjectRequest(
            source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
            identity_key={"source_date": "2026-01-01"},
        )
    ]

    def publish_one(result, ctx) -> PublishResult:
        return PublishResult(
            success=True,
            source_date="2026-01-01",
            write_metrics=(
                DuckLakeWriteMetrics(
                    table=RawDuckLakeTable.MARKET_HISTORY,
                    mode=DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
                    attempted_rows=10,
                    inserted_rows=7,
                    matched_rows=3,
                    replaced_rows=0,
                ),
            ),
        )

    pipeline_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="eve_ingest.publication.runner"):
            exit_code = run_dataset_pipeline(
                spec=MARKET_HISTORY_SPEC,
                discover_objects=lambda config: objects,
                config=config,
                publish_one=publish_one,
            )
    finally:
        pipeline_logger.removeHandler(caplog.handler)

    assert exit_code == 0
    assert "Pipeline summary dataset=market-history success=1 failed=0 marked_published=1" in caplog.text


def test_run_pipeline_rejects_writer_mode_mismatch_before_marking_published(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None)

    class FakeStore(_FakeStore):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            captured.pubtrack = self.pubtrack

    monkeypatch.setattr("eve_ingest.publication.runner.RawObjectStore", FakeStore)
    monkeypatch.setattr("eve_ingest.raw_objects.store.RawObjectStore", FakeStore)

    monkeypatch.setattr(
        "eve_ingest.publication.runner.hold_ducklake_lock_domains",
        lambda *, catalog_url, lock_domains, timeout_seconds, context: _FakeLock(lock_domains),
    )
    monkeypatch.setattr("eve_ingest.publication.runner.DuckLakeSession", _FakeSession)
    monkeypatch.setattr("eve_ingest.publication.runner.RawTablePublisher", _FakeRawTablePublisher)
    monkeypatch.setattr("eve_ingest.publication.runner.SourceObjectProvenanceRepository", _FakeProvenanceRepository)

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [RawObjectRequest(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]

    def publish_one(result, ctx) -> PublishResult:
        ctx.replace_reference_tables(
            result,
            source_system="everef",
            endpoint="market_history",
            source_market_date=__import__("datetime").date(2026, 1, 1),
            prepared_tables=[],
            provenance_table=RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS,
        )
        return PublishResult(success=True, source_date="2026-01-01")

    exit_code = run_dataset_pipeline(
        spec=MARKET_HISTORY_SPEC,
        discover_objects=lambda config: objects,
        config=config,
        publish_one=publish_one,
    )

    assert exit_code == 1
    assert captured.pubtrack is not None
    assert len(captured.pubtrack.calls) == 0


def test_build_publication_scope_returns_expected_scope_strings() -> None:
    assert MARKET_ORDERS_SPEC.scope_for({"source_date": "2026-01-01"}) == ("raw:market_orders:source_date=2026-01-01")
    assert FUZZWORK_ORDERS_SPEC.scope_for({"source_date": "2026-01-01"}) == (
        "raw:fuzzwork_orders:source_date=2026-01-01"
    )
    assert MARKET_HISTORY_SPEC.scope_for({"source_date": "2026-01-01"}) == ("raw:market_history:source_date=2026-01-01")
    assert REFERENCES_SPEC.scope_for({"source_date": "latest"}) == "raw:references:full_extract"


def test_run_pipeline_locks_per_scope_and_threads_publication_context(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(scopes=[], pubtrack=None)

    class FakeStore(_FakeStore):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            captured.pubtrack = self.pubtrack

        def acquire_many(self, objects: list[RawObjectRequest]) -> list[AcquiredRawObject]:
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

    monkeypatch.setattr("eve_ingest.publication.runner.RawObjectStore", FakeStore)
    monkeypatch.setattr("eve_ingest.raw_objects.store.RawObjectStore", FakeStore)
    monkeypatch.setattr("eve_ingest.publication.runner.DuckLakeSession", _FakeSession)
    monkeypatch.setattr("eve_ingest.publication.runner.RawTablePublisher", _FakeRawTablePublisher)
    monkeypatch.setattr("eve_ingest.publication.runner.SourceObjectProvenanceRepository", _FakeProvenanceRepository)

    def hold_scope_locks(*, catalog_url, lock_domains, timeout_seconds, context):
        captured.scopes.append((context.dataset, lock_domains, context.source_date))
        return _FakeLock(lock_domains)

    monkeypatch.setattr(
        "eve_ingest.publication.runner.hold_ducklake_lock_domains",
        hold_scope_locks,
    )
    monkeypatch.setenv("AIRFLOW_CTX_RUN_ID", "airflow-run-123")

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [
        RawObjectRequest(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"}),
        RawObjectRequest(source_url="https://example.com/b.csv.bz2", identity_key={"source_date": "2026-01-02"}),
    ]

    def publish_one(result, ctx) -> PublishResult:
        return PublishResult(success=True, source_date=str(result.identity_key["source_date"]))

    exit_code = run_dataset_pipeline(
        spec=MARKET_HISTORY_SPEC,
        discover_objects=lambda config: objects,
        config=config,
        publish_one=publish_one,
    )

    assert exit_code == 0
    assert len(captured.scopes) == 2
    assert captured.scopes[0][0] == "market-history"
    assert captured.scopes[1][0] == "market-history"
    assert captured.pubtrack is not None
    assert len(captured.pubtrack.calls) == 2
    contexts = [publication_scope for _, publication_scope, _ in captured.pubtrack.calls]
    assert contexts == [
        "raw:market_history:source_date=2026-01-01",
        "raw:market_history:source_date=2026-01-02",
    ]


def test_run_pipeline_fails_whole_run_on_publication_lock_contention(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None, process_calls=0)

    class FakeStore(_FakeStore):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            captured.pubtrack = self.pubtrack

        def acquire_many(self, objects: list[RawObjectRequest]) -> list[AcquiredRawObject]:
            return [
                make_cache_result(
                    "/tmp/a.csv.bz2",
                    dataset_name="market-history",
                    identity_key={"source_date": "2026-01-01"},
                )
            ]

    monkeypatch.setattr("eve_ingest.publication.runner.RawObjectStore", FakeStore)
    monkeypatch.setattr("eve_ingest.raw_objects.store.RawObjectStore", FakeStore)
    monkeypatch.setattr(
        "eve_ingest.publication.runner.hold_ducklake_lock_domains",
        lambda *, catalog_url, lock_domains, timeout_seconds, context: (_ for _ in ()).throw(
            DuckLakeLockTimeoutError("busy")
        ),
    )
    monkeypatch.setattr("eve_ingest.publication.runner.DuckLakeSession", _FakeSession)
    monkeypatch.setattr("eve_ingest.publication.runner.RawTablePublisher", _FakeRawTablePublisher)
    monkeypatch.setattr("eve_ingest.publication.runner.SourceObjectProvenanceRepository", _FakeProvenanceRepository)

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [RawObjectRequest(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]

    def publish_one(result, ctx) -> PublishResult:
        captured.process_calls += 1
        return PublishResult(success=True, source_date="2026-01-01")

    with pytest.raises(DuckLakeLockTimeoutError, match="busy"):
        run_dataset_pipeline(
            spec=MARKET_HISTORY_SPEC,
            discover_objects=lambda config: objects,
            config=config,
            publish_one=publish_one,
        )

    assert captured.process_calls == 0
    assert captured.pubtrack is not None
    assert len(captured.pubtrack.calls) == 0


def test_run_pipeline_rechecks_publication_after_lock_and_skips(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None, process_calls=0, writer_constructed=False)

    shared_published_versions: set[tuple[str, str]] = set()

    class FakeStore(_FakeStore):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.pubtrack.published_versions = shared_published_versions
            captured.pubtrack = self.pubtrack

        def acquire_many(self, objects: list[RawObjectRequest]) -> list[AcquiredRawObject]:
            path = self.raw_root / "a.csv.bz2"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("data")
            result = make_cache_result(
                str(path),
                dataset_name="market-history",
                identity_key={"source_date": "2026-01-01"},
                update_mode=UpdateMode.MUTABLE,
            )
            shared_published_versions.add((result.raw_object.ref.identity_hash, result.version.sha256))
            return [result]

        def load_current_states_for_results(self, results: list[AcquiredRawObject]):
            raise AssertionError("already-published results should be skipped before current-state lookup")

    class FakeSession(_FakeSession):
        def __init__(self, *args, **kwargs) -> None:
            captured.writer_constructed = True
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("eve_ingest.publication.runner.RawObjectStore", FakeStore)
    monkeypatch.setattr("eve_ingest.raw_objects.store.RawObjectStore", FakeStore)
    monkeypatch.setattr(
        "eve_ingest.publication.runner.hold_ducklake_lock_domains",
        lambda *, catalog_url, lock_domains, timeout_seconds, context: _FakeLock(lock_domains),
    )
    monkeypatch.setattr("eve_ingest.publication.runner.DuckLakeSession", FakeSession)
    monkeypatch.setattr("eve_ingest.publication.runner.RawTablePublisher", _FakeRawTablePublisher)
    monkeypatch.setattr("eve_ingest.publication.runner.SourceObjectProvenanceRepository", _FakeProvenanceRepository)

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [RawObjectRequest(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]

    def publish_one(result, ctx) -> PublishResult:
        captured.process_calls += 1
        return PublishResult(success=True, source_date="2026-01-01")

    assert (
        run_dataset_pipeline(
            spec=MARKET_HISTORY_SPEC,
            discover_objects=lambda config: objects,
            config=config,
            publish_one=publish_one,
        )
        == 0
    )
    assert captured.process_calls == 0
    assert captured.writer_constructed is False
    assert captured.pubtrack is not None
    assert len(captured.pubtrack.calls) == 0


def test_run_pipeline_skips_stale_mutable_result_after_lock(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None, process_calls=0, writer_constructed=False)

    class FakeStore(_FakeStore):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            captured.pubtrack = self.pubtrack

        def acquire_many(self, objects: list[RawObjectRequest]) -> list[AcquiredRawObject]:
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
            self, results: list[AcquiredRawObject]
        ) -> dict[str, CurrentRawObjectState | None]:
            result = results[0]
            current_version = replace(result.version, id="ver-2", sha256="def456")
            return {
                result.raw_object.ref.identity_hash: CurrentRawObjectState(
                    raw_object=result.raw_object,
                    current_version=current_version,
                )
            }

    class FakeSession(_FakeSession):
        def __init__(self, *args, **kwargs) -> None:
            captured.writer_constructed = True
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("eve_ingest.publication.runner.RawObjectStore", FakeStore)
    monkeypatch.setattr("eve_ingest.raw_objects.store.RawObjectStore", FakeStore)

    monkeypatch.setattr(
        "eve_ingest.publication.runner.hold_ducklake_lock_domains",
        lambda *, catalog_url, lock_domains, timeout_seconds, context: _FakeLock(lock_domains),
    )
    monkeypatch.setattr("eve_ingest.publication.runner.DuckLakeSession", FakeSession)
    monkeypatch.setattr("eve_ingest.publication.runner.RawTablePublisher", _FakeRawTablePublisher)
    monkeypatch.setattr("eve_ingest.publication.runner.SourceObjectProvenanceRepository", _FakeProvenanceRepository)

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [RawObjectRequest(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]

    def publish_one(result, ctx) -> PublishResult:
        captured.process_calls += 1
        return PublishResult(success=True, source_date="2026-01-01")

    assert (
        run_dataset_pipeline(
            spec=MARKET_HISTORY_SPEC,
            discover_objects=lambda config: objects,
            config=config,
            publish_one=publish_one,
        )
        == 0
    )
    assert captured.process_calls == 0
    assert captured.writer_constructed is False
    assert captured.pubtrack is not None
    assert len(captured.pubtrack.calls) == 0


def test_run_pipeline_skips_stale_mutable_result_with_missing_file_after_lock(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None, process_calls=0, writer_constructed=False)

    class FakeStore(_FakeStore):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            captured.pubtrack = self.pubtrack

        def acquire_many(self, objects: list[RawObjectRequest]) -> list[AcquiredRawObject]:
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
            self, results: list[AcquiredRawObject]
        ) -> dict[str, CurrentRawObjectState | None]:
            result = results[0]
            current_version = replace(result.version, id="ver-2", sha256="def456")
            return {
                result.raw_object.ref.identity_hash: CurrentRawObjectState(
                    raw_object=result.raw_object,
                    current_version=current_version,
                )
            }

    class FakeSession(_FakeSession):
        def __init__(self, *args, **kwargs) -> None:
            captured.writer_constructed = True
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("eve_ingest.publication.runner.RawObjectStore", FakeStore)
    monkeypatch.setattr("eve_ingest.raw_objects.store.RawObjectStore", FakeStore)

    monkeypatch.setattr(
        "eve_ingest.publication.runner.hold_ducklake_lock_domains",
        lambda *, catalog_url, lock_domains, timeout_seconds, context: _FakeLock(lock_domains),
    )
    monkeypatch.setattr("eve_ingest.publication.runner.DuckLakeSession", FakeSession)
    monkeypatch.setattr("eve_ingest.publication.runner.RawTablePublisher", _FakeRawTablePublisher)
    monkeypatch.setattr("eve_ingest.publication.runner.SourceObjectProvenanceRepository", _FakeProvenanceRepository)

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [RawObjectRequest(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]

    def publish_one(result, ctx) -> PublishResult:
        captured.process_calls += 1
        return PublishResult(success=True, source_date="2026-01-01")

    assert (
        run_dataset_pipeline(
            spec=MARKET_HISTORY_SPEC,
            discover_objects=lambda config: objects,
            config=config,
            publish_one=publish_one,
        )
        == 0
    )
    assert captured.process_calls == 0
    assert captured.writer_constructed is False
    assert captured.pubtrack is not None
    assert len(captured.pubtrack.calls) == 0


def test_run_pipeline_skips_stale_reference_latest_result_after_lock(monkeypatch, tmp_path: Path) -> None:
    captured: SimpleNamespace = SimpleNamespace(pubtrack=None, process_calls=0, writer_constructed=False)

    class FakeStore(_FakeStore):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            captured.pubtrack = self.pubtrack

        def acquire_many(self, objects: list[RawObjectRequest]) -> list[AcquiredRawObject]:
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
            self, results: list[AcquiredRawObject]
        ) -> dict[str, CurrentRawObjectState | None]:
            result = results[0]
            current_version = replace(result.version, id="ver-2", sha256="def456")
            return {
                result.raw_object.ref.identity_hash: CurrentRawObjectState(
                    raw_object=result.raw_object,
                    current_version=current_version,
                )
            }

    class FakeSession(_FakeSession):
        def __init__(self, *args, **kwargs) -> None:
            captured.writer_constructed = True
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("eve_ingest.publication.runner.RawObjectStore", FakeStore)
    monkeypatch.setattr("eve_ingest.raw_objects.store.RawObjectStore", FakeStore)

    monkeypatch.setattr(
        "eve_ingest.publication.runner.hold_ducklake_lock_domains",
        lambda *, catalog_url, lock_domains, timeout_seconds, context: _FakeLock(lock_domains),
    )
    monkeypatch.setattr("eve_ingest.publication.runner.DuckLakeSession", FakeSession)
    monkeypatch.setattr("eve_ingest.publication.runner.RawTablePublisher", _FakeRawTablePublisher)
    monkeypatch.setattr("eve_ingest.publication.runner.SourceObjectProvenanceRepository", _FakeProvenanceRepository)

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [
        RawObjectRequest(
            source_url="https://data.everef.net/reference-data/reference-data-latest.tar.xz",
            identity_key={"source_date": "latest"},
        )
    ]

    def publish_one(result, ctx) -> PublishResult:
        captured.process_calls += 1
        return PublishResult(success=True, source_date="latest")

    assert (
        run_dataset_pipeline(
            spec=REFERENCES_SPEC,
            discover_objects=lambda config: objects,
            config=config,
            publish_one=publish_one,
        )
        == 0
    )
    assert captured.process_calls == 0
    assert captured.writer_constructed is False
    assert captured.pubtrack is not None
    assert len(captured.pubtrack.calls) == 0


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
    pubtrack_calls: list[list[AcquiredRawObject]] = []
    process_calls = 0
    writer_constructed = 0

    class SharedPubtrack:
        def filter_published(self, results: list[AcquiredRawObject]) -> set[tuple[str, str]]:
            with pubtrack_lock:
                return set(published_versions)

        def filter_unpublished(self, results: list[AcquiredRawObject]) -> list[AcquiredRawObject]:
            published = self.filter_published(results)
            return [r for r in results if (r.raw_object.ref.identity_hash, r.version.sha256) not in published]

        def mark_published_many(
            self,
            results: list[AcquiredRawObject],
            *,
            context: PublicationContext | None = None,
        ) -> None:
            with pubtrack_lock:
                pubtrack_calls.append(results)
                for published_result in results:
                    published_versions.add(
                        (published_result.raw_object.ref.identity_hash, published_result.version.sha256)
                    )

    shared_pubtrack = SharedPubtrack()

    class SharedStore:
        pubtrack = shared_pubtrack

        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> SharedStore:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        @property
        def ledger(self) -> object:
            return None

        def acquire_many(self, objects: list[RawObjectRequest]) -> list[AcquiredRawObject]:
            selected.wait(timeout=5)
            return [result]

        def load_current_states_for_results(
            self, results: list[AcquiredRawObject]
        ) -> dict[str, CurrentRawObjectState | None]:
            return {
                selected_result.raw_object.ref.identity_hash: CurrentRawObjectState(
                    raw_object=selected_result.raw_object,
                    current_version=selected_result.version,
                )
                for selected_result in results
            }

        def filter_current_versions(self, results: list[AcquiredRawObject]) -> tuple[list[AcquiredRawObject], int, int]:
            return results, 0, 0

    class SerialLock:
        def __init__(self, lock_domains: tuple[str, ...]) -> None:
            self.lock_domains = lock_domains

        def __enter__(self):
            publication_lock.acquire()
            return DuckLakeLockToken.unsafe_for_tests(self.lock_domains)

        def __exit__(self, exc_type, exc, tb) -> None:
            publication_lock.release()

    class CountingSession(_FakeSession):
        def __init__(self, *args, **kwargs) -> None:
            nonlocal writer_constructed
            writer_constructed += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("eve_ingest.publication.runner.RawObjectStore", SharedStore)
    monkeypatch.setattr("eve_ingest.raw_objects.store.RawObjectStore", SharedStore)
    monkeypatch.setattr(
        "eve_ingest.publication.runner.hold_ducklake_lock_domains",
        lambda *, catalog_url, lock_domains, timeout_seconds, context: SerialLock(lock_domains),
    )
    monkeypatch.setattr("eve_ingest.publication.runner.DuckLakeSession", CountingSession)
    monkeypatch.setattr("eve_ingest.publication.runner.RawTablePublisher", _FakeRawTablePublisher)
    monkeypatch.setattr("eve_ingest.publication.runner.SourceObjectProvenanceRepository", _FakeProvenanceRepository)

    config = make_everef_pipeline_config(EverefReferencesCliConfig, tmp_path)
    objects = [RawObjectRequest(source_url="https://example.com/a.csv.bz2", identity_key={"source_date": "2026-01-01"})]
    exit_codes: list[int] = []
    errors: list[BaseException] = []

    def publish_one(result, ctx) -> PublishResult:
        nonlocal process_calls
        process_calls += 1
        return PublishResult(success=True, source_date="2026-01-01")

    def worker() -> None:
        try:
            exit_codes.append(
                run_dataset_pipeline(
                    spec=MARKET_HISTORY_SPEC,
                    discover_objects=lambda config: objects,
                    config=config,
                    publish_one=publish_one,
                )
            )
        except BaseException as exc:
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
