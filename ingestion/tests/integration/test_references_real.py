from __future__ import annotations

import json
import tarfile
from typing import TYPE_CHECKING

import duckdb
import pytest
from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig
from eve_ingest.ducklake.bootstrap import bootstrap_raw_ducklake
from eve_ingest.ducklake.locks import DuckLakeLockToken, ducklake_lock_domains_for_tables
from eve_ingest.ducklake.provenance import SourceObjectProvenanceRepository
from eve_ingest.ducklake.raw_publish import RawTablePublisher
from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.ducklake.session import DuckLakeSession
from eve_ingest.publication.context import PublishContext
from eve_ingest.publication.service import PublicationService
from eve_ingest.publication.source_prep import SourcePreparationContext
from eve_ingest.publication.specs import DatasetPublisherSpec, ReplaceReferenceTables, StaticScope
from eve_ingest.raw_objects import UpdateMode
from eve_ingest.sources.everef.reference_data import publish_one
from tests.sources.everef.conftest import make_cache_result

if TYPE_CHECKING:
    from pathlib import Path


class _KeepConnection:
    def __init__(self) -> None:
        self._con = duckdb.connect(":memory:")

    def __getattr__(self, name: str):
        return getattr(self._con, name)

    def close(self) -> None:
        pass


@pytest.fixture
def shared_con(monkeypatch):
    con = _KeepConnection()
    monkeypatch.setattr("eve_ingest.ducklake.session.duckdb.connect", lambda: con)
    monkeypatch.setattr("eve_ingest.ducklake.bootstrap.duckdb.connect", lambda: con)
    monkeypatch.setattr("eve_ingest.ducklake.session.DuckLakeSession._attach", lambda self: None)
    monkeypatch.setattr("eve_ingest.ducklake.bootstrap._attach_bootstrap", lambda c, config: None)
    yield con._con
    con._con.close()


_ATTACH = DuckLakeAttachConfig(
    attach_uri=":memory:",
    data_path="",
    metadata_schema="memory",
    alias="memory",
)


def _test_lock_token() -> DuckLakeLockToken:
    return DuckLakeLockToken.unsafe_for_tests(
        ducklake_lock_domains_for_tables(
            data_tables=tuple(RawDuckLakeTable),
            provenance_tables=tuple(RawDuckLakeProvenanceTable),
        )
    )


@pytest.fixture(autouse=True)
def bootstrapped(shared_con) -> None:
    bootstrap_raw_ducklake(_ATTACH)


def _make_tarball(path: Path, files: dict[str, str]) -> Path:
    staging = path.parent / "staging"
    staging.mkdir(exist_ok=True)
    for name, content in files.items():
        file_path = staging / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)

    with tarfile.open(path, "w:xz") as archive:
        for file_path in staging.rglob("*"):
            if file_path.is_file():
                archive.add(file_path, arcname=str(file_path.relative_to(staging)))
    return path


@pytest.mark.real_duckdb
def test_process_references_result_writes_real_tables(shared_con, tmp_path: Path) -> None:
    archive_path = tmp_path / "reference-data-latest.tar.xz"
    _make_tarball(
        archive_path,
        {
            "types.json": json.dumps(
                {
                    "1": {"type_id": 1, "name": {"en": "foo"}, "group_id": 10, "category_id": 20, "published": True},
                    "2": {"type_id": 2, "name": {"en": "bar"}, "group_id": 11, "category_id": 21, "published": True},
                }
            ),
            "regions.json": json.dumps(
                {
                    "10000001": {
                        "region_id": 10000001,
                        "name": {"en": "The Forge"},
                        "description": {"en": "Trade hub region"},
                        "universe_id": "eve",
                        "faction_id": 500001,
                        "wormhole_class_id": 7,
                    }
                }
            ),
            "market_groups.json": json.dumps(
                {
                    "1857": {
                        "market_group_id": 1857,
                        "name": {"en": "Minerals"},
                        "description": {"en": "Mined goods"},
                        "parent_group_id": 533,
                        "has_types": True,
                        "icon_id": 404,
                    }
                }
            ),
        },
    )

    spec = DatasetPublisherSpec(
        dataset_name="reference-data",
        update_mode=UpdateMode.MUTABLE,
        data_tables=(
            RawDuckLakeTable.REFERENCE_TYPES,
            RawDuckLakeTable.REFERENCE_REGIONS,
            RawDuckLakeTable.REFERENCE_GROUPS,
            RawDuckLakeTable.REFERENCE_CATEGORIES,
            RawDuckLakeTable.REFERENCE_MARKET_GROUPS,
        ),
        provenance_tables=(RawDuckLakeProvenanceTable.REFERENCE_OBJECTS,),
        publication_scope=StaticScope("raw:references:full_extract"),
        write_policy=ReplaceReferenceTables(),
    )
    result = make_cache_result(
        str(archive_path),
        dataset_name="reference-data",
        identity_key={"source_date": "latest"},
        source_url="https://data.everef.net/reference-data/reference-data-latest.tar.xz",
    )
    lock_token = _test_lock_token()
    with DuckLakeSession(_ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(session, lock_token=lock_token)
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(
            raw_tables=raw_tables,
            provenance=provenance,
            session=session,
            spec=spec,
        )
        ctx = PublishContext(
            spec=spec,
            prep_ctx=prep_ctx,
            service=service,
            publication_scope="raw:references:full_extract",
        )
        outcome = publish_one(result, ctx)

    assert outcome.success is True
    assert outcome.source_date == "latest"
    assert len(outcome.write_metrics) == 3

    types = shared_con.execute(
        f'SELECT type_id, name_en, group_id, category_id, published FROM "memory"."raw"."{RawDuckLakeTable.REFERENCE_TYPES.value}" ORDER BY type_id'
    ).fetchall()
    regions = shared_con.execute(
        f'SELECT region_id, name_en, universe_id, faction_id, wormhole_class_id FROM "memory"."raw"."{RawDuckLakeTable.REFERENCE_REGIONS.value}" ORDER BY region_id'
    ).fetchall()
    market_groups = shared_con.execute(
        f'SELECT market_group_id, name_en, parent_group_id, has_types FROM "memory"."raw"."{RawDuckLakeTable.REFERENCE_MARKET_GROUPS.value}" ORDER BY market_group_id'
    ).fetchall()

    assert types == [(1, "foo", 10, 20, True), (2, "bar", 11, 21, True)]
    assert regions == [(10000001, "The Forge", "eve", 500001, 7)]
    assert market_groups == [(1857, "Minerals", 533, True)]

    # Verify no provenance columns on reference row tables
    type_cols = [
        r[0]
        for r in shared_con.execute(
            f"SELECT column_name FROM information_schema.columns WHERE table_name='{RawDuckLakeTable.REFERENCE_TYPES.value}'"
        ).fetchall()
    ]
    for col in type_cols:
        assert not col.startswith("_source"), f"Reference table should not have provenance column: {col}"

    # Verify dataset-scoped provenance has an entry for the archive
    so_entries = shared_con.execute(
        f'SELECT source_ref_id, source_system, endpoint, status FROM "memory"."raw"."{RawDuckLakeProvenanceTable.REFERENCE_OBJECTS.value}"'
    ).fetchall()
    assert len(so_entries) == 1
    assert so_entries[0][1] == "everef"
    assert so_entries[0][2] == "reference_data"
    assert so_entries[0][3] == "ingested"


@pytest.mark.real_duckdb
def test_process_references_result_marks_failed_on_archive_error(shared_con, tmp_path: Path) -> None:
    broken_path = tmp_path / "broken-reference-data.tar.xz"
    broken_path.write_text("not a tar archive")

    spec = DatasetPublisherSpec(
        dataset_name="reference-data",
        update_mode=UpdateMode.MUTABLE,
        data_tables=(RawDuckLakeTable.REFERENCE_TYPES,),
        provenance_tables=(RawDuckLakeProvenanceTable.REFERENCE_OBJECTS,),
        publication_scope=StaticScope("raw:references:full_extract"),
        write_policy=ReplaceReferenceTables(),
    )
    result = make_cache_result(
        str(broken_path),
        dataset_name="reference-data",
        identity_key={"source_date": "latest"},
        source_url="https://data.everef.net/reference-data/reference-data-latest.tar.xz",
    )
    lock_token = _test_lock_token()
    with DuckLakeSession(_ATTACH, lock_token=lock_token) as session:
        raw_tables = RawTablePublisher(session, lock_token=lock_token)
        provenance = SourceObjectProvenanceRepository(session, lock_token=lock_token)
        prep_ctx = SourcePreparationContext(session=session)
        service = PublicationService(
            raw_tables=raw_tables,
            provenance=provenance,
            session=session,
            spec=spec,
        )
        ctx = PublishContext(
            spec=spec,
            prep_ctx=prep_ctx,
            service=service,
            publication_scope="raw:references:full_extract",
        )
        with pytest.raises((ValueError, RuntimeError, tarfile.ReadError)):
            publish_one(result, ctx)
