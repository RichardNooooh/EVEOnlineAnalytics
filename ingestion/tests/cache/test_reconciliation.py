from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from eve_ingest.raw_objects.reconciliation import RawFileReconciler
from tests.cache.fakes import InMemoryRawObjectLedger


def _make_ledger_with_paths(paths: list[str]) -> InMemoryRawObjectLedger:
    ledger = InMemoryRawObjectLedger()
    for i, p in enumerate(paths):
        from uuid import uuid4

        from eve_ingest.raw_objects.http_models import RevalidationMetadata
        from eve_ingest.raw_objects.ledger.models import RawObjectVersion

        version = RawObjectVersion(
            id=uuid4().hex,
            raw_object_id="obj-orphan",
            source_url="https://example.com/file.csv",
            fetched_at=datetime.now(UTC),
            revalidation=RevalidationMetadata(),
            sha256="abc",
            local_path=p,
            storage_encoding="raw",
            version_number=i,
        )
        ledger._versions_by_object_id.setdefault("obj-orphan", []).append(version)
    return ledger


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"data")


def test_list_files_on_disk_empty(tmp_path: Path) -> None:
    ledger = InMemoryRawObjectLedger()
    reconciler = RawFileReconciler(raw_root=tmp_path / "raw", ledger=ledger)  # ty: ignore[invalid-argument-type]
    assert reconciler.list_files_on_disk() == []


def test_list_files_on_disk_skips_temp(tmp_path: Path) -> None:
    ledger = InMemoryRawObjectLedger()
    reconciler = RawFileReconciler(raw_root=tmp_path / "raw", ledger=ledger)  # ty: ignore[invalid-argument-type]
    _touch(tmp_path / "raw" / "everef" / "file.csv")
    _touch(tmp_path / "raw" / ".tmp" / "everef" / "download.tmp")
    files = reconciler.list_files_on_disk()
    assert len(files) == 1
    assert files[0] == tmp_path / "raw" / "everef" / "file.csv"


def test_list_ledger_paths(tmp_path: Path) -> None:
    ledger = _make_ledger_with_paths(["/ledger/file1.csv", "/ledger/file2.csv"])
    reconciler = RawFileReconciler(raw_root=tmp_path / "raw", ledger=ledger)  # ty: ignore[invalid-argument-type]
    assert reconciler.list_ledger_paths() == {"/ledger/file1.csv", "/ledger/file2.csv"}


def test_find_orphans_none(tmp_path: Path) -> None:
    tracked = str(tmp_path / "raw" / "everef" / "file.csv")
    ledger = _make_ledger_with_paths([tracked])
    _touch(Path(tracked))
    reconciler = RawFileReconciler(raw_root=tmp_path / "raw", ledger=ledger)  # ty: ignore[invalid-argument-type]
    assert reconciler.find_orphans() == []


def test_find_orphans_some(tmp_path: Path) -> None:
    tracked = str(tmp_path / "raw" / "everef" / "tracked.csv")
    orphan_path = tmp_path / "raw" / "everef" / "orphan.csv"
    ledger = _make_ledger_with_paths([tracked])
    _touch(Path(tracked))
    _touch(orphan_path)
    reconciler = RawFileReconciler(raw_root=tmp_path / "raw", ledger=ledger)  # ty: ignore[invalid-argument-type]
    orphans = reconciler.find_orphans()
    assert orphan_path in orphans
    assert Path(tracked) not in orphans


def test_find_orphans_with_retention(tmp_path: Path) -> None:
    tracked = str(tmp_path / "raw" / "everef" / "tracked.csv")
    old_orphan = tmp_path / "raw" / "everef" / "old_orphan.csv"
    new_orphan = tmp_path / "raw" / "everef" / "new_orphan.csv"
    ledger = _make_ledger_with_paths([tracked])
    _touch(Path(tracked))
    _touch(old_orphan)
    _touch(new_orphan)

    old_ts = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    old_orphan.touch()
    old_orphan.stat()
    import os

    os.utime(str(old_orphan), (old_ts, old_ts))

    reconciler = RawFileReconciler(raw_root=tmp_path / "raw", ledger=ledger)  # ty: ignore[invalid-argument-type]
    orphans = reconciler.find_orphans(older_than=timedelta(days=7))
    assert old_orphan in orphans
    assert new_orphan not in orphans


def test_delete_orphans(tmp_path: Path) -> None:
    tracked = str(tmp_path / "raw" / "everef" / "tracked.csv")
    orphan_path = tmp_path / "raw" / "everef" / "orphan.csv"
    ledger = _make_ledger_with_paths([tracked])
    _touch(Path(tracked))
    _touch(orphan_path)
    reconciler = RawFileReconciler(raw_root=tmp_path / "raw", ledger=ledger)  # ty: ignore[invalid-argument-type]
    count = reconciler.delete_orphans()
    assert count == 1
    assert not orphan_path.exists()
    assert Path(tracked).exists()


def test_delete_orphans_respects_retention(tmp_path: Path) -> None:
    tracked = str(tmp_path / "raw" / "everef" / "tracked.csv")
    old_orphan = tmp_path / "raw" / "everef" / "old_orphan.csv"
    new_orphan = tmp_path / "raw" / "everef" / "new_orphan.csv"
    ledger = _make_ledger_with_paths([tracked])
    _touch(Path(tracked))
    _touch(old_orphan)
    _touch(new_orphan)

    old_ts = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    import os

    os.utime(str(old_orphan), (old_ts, old_ts))

    reconciler = RawFileReconciler(raw_root=tmp_path / "raw", ledger=ledger)  # ty: ignore[invalid-argument-type]
    count = reconciler.delete_orphans(older_than=timedelta(days=7))
    assert count == 1
    assert not old_orphan.exists()
    assert new_orphan.exists()


def test_list_files_on_disk_when_raw_root_missing(tmp_path: Path) -> None:
    ledger = InMemoryRawObjectLedger()
    reconciler = RawFileReconciler(raw_root=tmp_path / "nonexistent", ledger=ledger)  # ty: ignore[invalid-argument-type]
    assert reconciler.list_files_on_disk() == []
