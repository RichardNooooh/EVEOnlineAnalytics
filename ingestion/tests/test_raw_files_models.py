from __future__ import annotations

import hashlib
from pathlib import Path

from conftest import raw_file_record
from ingest.raw_files.models import cached_record_is_valid, local_file_matches


def test_cached_record_is_valid_accepts_matching_file(tmp_path: Path) -> None:
    path = tmp_path / "file.csv.bz2"
    content = b"raw bytes"
    path.write_bytes(content)
    record = raw_file_record(
        local_path=str(path),
        sha256=hashlib.sha256(content).hexdigest(),
        downloaded_size=len(content),
    )

    assert cached_record_is_valid(record)


def test_cached_record_is_valid_rejects_missing_local_path() -> None:
    assert not cached_record_is_valid(raw_file_record(local_path=None))


def test_cached_record_is_valid_rejects_missing_sha256(tmp_path: Path) -> None:
    path = tmp_path / "file.csv.bz2"
    path.write_bytes(b"raw bytes")

    assert not cached_record_is_valid(
        raw_file_record(local_path=str(path), sha256=None)
    )


def test_local_file_matches_rejects_size_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "file.csv.bz2"
    content = b"raw bytes"
    path.write_bytes(content)

    assert not local_file_matches(
        path,
        sha256=hashlib.sha256(content).hexdigest(),
        downloaded_size=len(content) + 1,
    )


def test_local_file_matches_rejects_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "file.csv.bz2"
    path.write_bytes(b"raw bytes")

    assert not local_file_matches(path, sha256="bad", downloaded_size=None)
