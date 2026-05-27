from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ingest.cache.models import BaseFetchPlan, RawObjectRef, UpdateMode
from ingest.cache.paths import (
    build_final_path,
    build_snapshot_path,
    build_temp_path,
    detect_storage_encoding,
    validate_path_segment,
)


def _plan(
    *,
    source_name: str = "everef",
    dataset_name: str = "market-orders",
    identity_hash: str = "abc123",
    source_relative_path: str = "market-orders/history/2026/2026-01-01/file.csv.bz2",
    update_mode: UpdateMode = UpdateMode.SNAPSHOT,
) -> BaseFetchPlan:
    return BaseFetchPlan(
        ref=RawObjectRef(
            source_name=source_name,
            dataset_name=dataset_name,
            identity_hash=identity_hash,
        ),
        source_url=f"https://data.everef.net/{source_relative_path}",
        source_relative_path=source_relative_path,
        update_mode=update_mode,
        identity_key={"source_path": source_relative_path},
        temp_path="/tmp/dummy",
    )


class TestBuildTempPath:
    def test_suffix_and_dir(self) -> None:
        path = build_temp_path(raw_root=Path("/data/raw"), source_name="everef")
        assert path.parent.parent == Path("/data/raw/everef")
        assert path.parent.name == ".tmp"
        assert path.suffix == ".download"
        assert len(path.stem) == 32  # uuid4 hex

    def test_rejects_bad_source_name(self) -> None:
        with pytest.raises(ValueError, match="must be a safe non-empty|must not contain"):
            build_temp_path(raw_root=Path("/data"), source_name="bad/name")


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
