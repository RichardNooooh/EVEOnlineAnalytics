from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from eve_ingest.cli.config import DuckLakeCliConfig, RawFilesCliConfig
from eve_ingest.ducklake.locks import DuckLakeLockToken
from eve_ingest.raw_objects import AcquiredRawObject, AcquisitionStatus
from eve_ingest.raw_objects.http_models import RevalidationMetadata
from eve_ingest.raw_objects.ledger.models import CurrentRawObjectState, RawObjectEntry, RawObjectRef, RawObjectVersion
from eve_ingest.raw_objects.models import AcquisitionMode
from eve_ingest.raw_objects.primitives import UpdateMode

if TYPE_CHECKING:
    import pyarrow as pa


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
        self.fetchone_results: list[tuple[object, ...] | None] = []
        self.provenance_objects: dict[str, dict[str, object]] = {}

    def execute(self, query: str, params: list[str] | None = None) -> FakeConnection:
        self.calls.append((query, params))
        self.fetchall_result = []
        normalized_query = " ".join(query.split()).upper()
        if normalized_query.startswith("MERGE INTO") and "SOURCE_REF_ID" in normalized_query and params:
            self.provenance_objects[str(params[0])] = {"source_ref_id": params[0]}
        elif normalized_query.startswith("UPDATE") and "SOURCE_REF_ID" in normalized_query and params:
            pass
        elif (
            normalized_query.startswith("SELECT 1")
            and "SOURCE_REF_ID" in normalized_query
            and "SHA256" in normalized_query
        ) or (normalized_query.startswith("SELECT SHA256") and "SOURCE_REF_ID" in normalized_query):
            self.fetchone_results.append(None)
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.fetchall_result

    def fetchone(self) -> tuple[object, ...] | None:
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
) -> AcquiredRawObject:
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
    return AcquiredRawObject(
        status=AcquisitionStatus.STORED,
        raw_object=raw_object,
        version=version,
    )


def make_everef_pipeline_config(config_cls: type[Any], tmp_path: Any, **kwargs: Any) -> Any:
    return config_cls(
        data_root=str(tmp_path),
        raw_files=RawFilesCliConfig(
            raw_root=str(tmp_path / "raw"),
            raw_ledger_url="postgresql://fake:fake@localhost:5432/fake",
            raw_download_workers=4,
        ),
        ducklake=DuckLakeCliConfig(
            ducklake_catalog="postgresql://fake:fake@localhost:5432/fake",
            ducklake_metadata_schema="test_schema",
            lock_wait_timeout_seconds=60.0,
            pg_pool_max_connections=32,
            pg_pool_wait_timeout_millis=120000,
            pg_pool_acquire_mode="wait",
        ),
        **kwargs,
    )


def install_pipeline_fakes(
    monkeypatch: Any,
    results: list[AcquiredRawObject],
    *,
    assert_mode: AcquisitionMode = AcquisitionMode.CHANGED,
) -> tuple[FakeConnection, MagicMock]:
    mock_pubtrack = MagicMock()
    mock_pubtrack.filter_published.return_value = set()
    mock_pubtrack.filter_unpublished.side_effect = lambda results: results

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

    class FakeRawObjectStore:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeRawObjectStore:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        @property
        def ledger(self) -> MagicMock:
            return MagicMock()

        @property
        def pubtrack(self) -> MagicMock:
            return mock_pubtrack

        def get_many(self, objects: object, *, mode: object = None) -> list[AcquiredRawObject]:
            assert mode is assert_mode
            return results

        def acquire_many(self, objects: object) -> list[AcquiredRawObject]:
            return results

        def load_current_states_for_results(
            self, selected: list[AcquiredRawObject]
        ) -> dict[str, CurrentRawObjectState | None]:
            return {
                result.raw_object.ref.identity_hash: CurrentRawObjectState(
                    raw_object=result.raw_object,
                    current_version=result.version,
                )
                for result in selected
            }

        def filter_current_versions(self, results: list[AcquiredRawObject]) -> tuple[list[AcquiredRawObject], int, int]:
            return results, 0, 0

    con = FakeConnection()
    monkeypatch.setattr("eve_ingest.ducklake.session.duckdb.connect", lambda: con)
    monkeypatch.setattr("eve_ingest.ducklake.raw_publish.target_exists", lambda *args, **kwargs: True)

    @contextmanager
    def fake_hold_ducklake_lock_domains(
        *,
        catalog_url: str = "",
        lock_domains: tuple[str, ...] = (),
        timeout_seconds: float = 60.0,
        context: object = None,
    ):
        yield DuckLakeLockToken.unsafe_for_tests(lock_domains)

    monkeypatch.setattr("eve_ingest.raw_objects.store.RawObjectStore", FakeRawObjectStore)
    monkeypatch.setattr("eve_ingest.publication.runner.RawObjectStore", FakeRawObjectStore)
    monkeypatch.setattr(
        "eve_ingest.publication.runner.hold_ducklake_lock_domains",
        fake_hold_ducklake_lock_domains,
    )
    return con, mock_pubtrack
