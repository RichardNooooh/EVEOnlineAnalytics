from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pyarrow as pa

from eve_ingest.raw_objects import CacheResult, CacheResultStatus
from eve_ingest.raw_objects.http_models import RevalidationMetadata
from eve_ingest.raw_objects.ledger.models import CurrentRawObjectState, RawObjectEntry, RawObjectRef, RawObjectVersion
from eve_ingest.raw_objects.primitives import UpdateMode
from eve_ingest.raw_objects.models import GetMode
from eve_ingest.cli.config import DuckLakeCliConfig, RawFilesCliConfig
from eve_ingest.ducklake.locks import DuckLakeLockToken


class FakeRelation:
    def __init__(self) -> None:
        self.view_names: list[str] = []

    def create_view(self, view_name: str) -> None:
        self.view_names.append(view_name)


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str] | None]] = []
        self.relation = FakeRelation()
        self.arrow_tables: list[pa.Table] = []
        self.closed = False
        self.fetchall_result: list[tuple[object, ...]] = []
        self.fetchone_results: list[tuple[object, ...]] = []

    def execute(self, query: str, params: list[str] | None = None) -> FakeConnection:
        self.calls.append((query, params))
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.fetchall_result

    def fetchone(self) -> tuple[object, ...]:
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return (0,)

    def from_arrow(self, arrow_table: pa.Table) -> FakeRelation:
        self.arrow_tables.append(arrow_table)
        return self.relation

    def close(self) -> None:
        self.closed = True


def make_cache_result(
    file_path: str,
    *,
    dataset_name: str = "market-history",
    identity_key: dict[str, Any] | None = None,
    source_url: str | None = None,
    content_length: int | None = None,
    last_modified: str | None = None,
    update_mode: UpdateMode = UpdateMode.SNAPSHOT,
    identity_hash: str = "abc",
    raw_object_id: str = "obj-1",
    version_id: str = "ver-1",
) -> CacheResult:
    identity_key = identity_key or {"source_date": "2026-01-01"}
    source_url = source_url or f"https://example.com/{dataset_name}/test.csv.bz2"

    ref = RawObjectRef(
        source_name="everef",
        dataset_name=dataset_name,
        identity_hash=identity_hash,
        identity_key=identity_key,
        update_mode=update_mode,
    )
    raw_object = RawObjectEntry(
        id=raw_object_id,
        ref=ref,
        created_at=datetime(2026, 1, 2, 11, 1, 55, tzinfo=UTC),
    )
    version = RawObjectVersion(
        id=version_id,
        raw_object_id=raw_object_id,
        source_url=source_url,
        fetched_at=datetime(2026, 1, 2, 11, 1, 55, tzinfo=UTC),
        revalidation=RevalidationMetadata(content_length=content_length, last_modified=last_modified),
        sha256="abc123",
        local_path=file_path,
        storage_encoding="bz2",
        version_number=1,
    )
    return CacheResult(
        status=CacheResultStatus.STORED,
        raw_object=raw_object,
        version=version,
    )


def make_everef_pipeline_config(config_cls: type[Any], tmp_path: Any, **kwargs: Any) -> Any:
    return config_cls(
        data_root=str(tmp_path),
        raw_files=RawFilesCliConfig(
            raw_root=str(tmp_path / "raw"),
            raw_ledger_url="postgresql://fake:fake@localhost:5432/fake",
        ),
        ducklake=DuckLakeCliConfig(
            ducklake_catalog="postgresql://fake:fake@localhost:5432/fake",
            ducklake_metadata_schema="test_schema",
            lock_wait_timeout_seconds=60.0,
        ),
        **kwargs,
    )


def install_pipeline_fakes(
    monkeypatch: Any,
    results: list[CacheResult],
    *,
    assert_mode: GetMode = GetMode.UNPUBLISHED,
) -> tuple[FakeConnection, MagicMock]:
    mock_pubtrack = MagicMock()
    mock_pubtrack.filter_published.return_value = set()

    @contextmanager
    def fake_hold_publication_domain_locks(
        *,
        publisher_spec: Any,
        catalog_url: str,
        publication_scopes: tuple[str, ...],
        source_date: str | None,
        timeout_seconds: float,
    ):
        yield DuckLakeLockToken.unsafe_for_tests(publisher_spec.lock_domains())

    class FakeCache:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeCache:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        @property
        def pubtrack(self) -> MagicMock:
            return mock_pubtrack

        def get_many(self, objects: object, *, mode: object = None) -> list[CacheResult]:
            assert mode is assert_mode
            return results

        def load_current_states_for_results(
            self, selected: list[CacheResult]
        ) -> dict[str, CurrentRawObjectState | None]:
            return {
                result.raw_object.ref.identity_hash: CurrentRawObjectState(
                    raw_object=result.raw_object,
                    current_version=result.version,
                )
                for result in selected
            }

    con = FakeConnection()
    monkeypatch.setattr("eve_ingest.ducklake.writer.duckdb.connect", lambda: con)
    monkeypatch.setattr("eve_ingest.ducklake.writer._target_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr("eve_ingest.workflows.raw_file_workflow.Cache", FakeCache)
    monkeypatch.setattr(
        "eve_ingest.workflows.raw_file_workflow._hold_publication_domain_locks",
        fake_hold_publication_domain_locks,
    )
    return con, mock_pubtrack
