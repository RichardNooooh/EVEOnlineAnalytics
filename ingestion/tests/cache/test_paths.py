from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from eve_ingest.raw_objects.fetch_plan import FetchPlan
from eve_ingest.raw_objects.ledger.models import RawObjectRef
from eve_ingest.raw_objects.paths import (
    build_final_path,
    build_snapshot_path,
    build_temp_path,
    detect_storage_encoding,
    validate_path_segment,
)
from eve_ingest.raw_objects.primitives import UpdateMode


def _plan(
    *,
    source_name: str = "everef",
    dataset_name: str = "market-orders",
    identity_hash: str = "abc123",
    source_relative_path: str = "market-orders/history/2026/2026-01-01/file.csv.bz2",
    update_mode: UpdateMode = UpdateMode.SNAPSHOT,
) -> FetchPlan:
    identity_key: dict[str, str] = {"source_path": source_relative_path}
    return FetchPlan(
        ref=RawObjectRef(
            source_name=source_name,
            dataset_name=dataset_name,
            identity_hash=identity_hash,
            identity_key=identity_key,
            update_mode=update_mode,
        ),
        source_url=f"https://data.everef.net/{source_relative_path}",
        source_relative_path=source_relative_path,
        temp_path="/tmp/dummy",
    )


class TestBuildTempPath:
    def test_suffix_and_dir(self) -> None:
        ref = RawObjectRef(
            source_name="everef",
            dataset_name="market-orders",
            identity_hash="abc123",
            identity_key={"source_path": "market-orders/history/2026/file.csv.bz2"},
            update_mode=UpdateMode.SNAPSHOT,
        )
        path = build_temp_path(raw_root=Path("/data/raw"), ref=ref)
        assert path.suffix == ".download"
        assert path.parent.name == "abc123"
        assert path.parent.parent.name == "market-orders"
        assert path.parent.parent.parent.name == "everef"
        assert path.parent.parent.parent.parent.name == ".tmp"
        assert path.parent.parent.parent.parent.parent == Path("/data/raw")

    def test_unique_per_call(self) -> None:
        ref = RawObjectRef(
            source_name="everef",
            dataset_name="market-orders",
            identity_hash="abc123",
            identity_key={"source_path": "market-orders/history/2026/file.csv.bz2"},
            update_mode=UpdateMode.SNAPSHOT,
        )
        path1 = build_temp_path(raw_root=Path("/data/raw"), ref=ref)
        path2 = build_temp_path(raw_root=Path("/data/raw"), ref=ref)
        assert path1.parent == path2.parent  # same identity_hash directory
        assert path1 != path2  # different UUID segment

    def test_rejects_bad_source_name(self) -> None:
        ref = RawObjectRef(
            source_name="bad/name",
            dataset_name="market-orders",
            identity_hash="abc123",
            identity_key={"source_path": "market-orders/history/2026/file.csv.bz2"},
            update_mode=UpdateMode.SNAPSHOT,
        )
        with pytest.raises(ValueError, match=r"must be a safe non-empty|must not contain"):
            build_temp_path(raw_root=Path("/data"), ref=ref)


class TestBuildSnapshotPath:
    def test_joins_source_and_relative_path(self) -> None:
        plan = _plan(source_relative_path="market-orders/history/2026/file.csv")
        path = build_snapshot_path(raw_root=Path("/data/raw"), plan=plan)
        assert path == Path("/data/raw/everef/market-orders/history/2026/file.csv")


class TestBuildFinalPath:
    def test_snapshot_delegates_to_snapshot_path(self) -> None:
        plan = _plan(update_mode=UpdateMode.SNAPSHOT)
        path = build_final_path(
            raw_root=Path("/data/raw"),
            plan=plan,
            fetched_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            sha256="abcdef1234567890",
        )
        assert path == Path("/data/raw/everef/market-orders/history/2026/2026-01-01/file.csv.bz2")

    def test_mutable_includes_timestamp_hash_and_uuid(self) -> None:
        plan = _plan(
            dataset_name="market-history",
            source_relative_path="market-history/2026-01-01.csv.bz2",
            update_mode=UpdateMode.MUTABLE,
        )
        path = build_final_path(
            raw_root=Path("/data/raw"),
            plan=plan,
            fetched_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            sha256="abcdef1234567890",
        )
        assert str(path).startswith("/data/raw/everef/market-history/objects/abc123/20260101T120000Z__abcdef123456__")
        assert str(path).endswith("__2026-01-01.csv.bz2")


class TestDetectStorageEncoding:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            (Path("file.csv.bz2"), "csv.bz2"),
            (Path("data.csv"), "csv"),
            (Path("archive.tar.gz"), "tar.gz"),
            (Path("noext"), "raw"),
            (Path("file."), "raw"),
        ],
    )
    def test_various_suffixes(self, path: Path, expected: str) -> None:
        assert detect_storage_encoding(path) == expected


class TestValidatePathSegment:
    @pytest.mark.parametrize("value", ["market-history", "everef", "a", "abc123"])
    def test_valid(self, value: str) -> None:
        assert validate_path_segment(value, field_name="test") == value

    @pytest.mark.parametrize(
        ("value", "match"),
        [
            ("", "must be a safe non-empty"),
            (".", "must be a safe non-empty"),
            ("..", "must be a safe non-empty"),
            ("a/b", "must not contain path separators"),
            ("a\\b", "must not contain path separators"),
        ],
    )
    def test_invalid(self, value: str, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            validate_path_segment(value, field_name="test")
