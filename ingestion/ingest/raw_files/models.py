"""Raw source-file acquisition models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ingest.raw_files.downloader import sha256_file


@dataclass(frozen=True)
class RawFileRecord:
    """One raw source-file ledger row."""

    id: int | None
    source_name: str
    dataset_name: str
    source_date: str
    source_url: str
    local_path: str | None
    sha256: str | None
    content_length: int | None
    downloaded_size: int | None
    last_modified: str | None
    etag: str | None
    source_row_count: int | None
    first_seen_at: str
    last_checked_at: str
    downloaded_at: str | None
    status: str
    error_message: str | None = None


def cached_record_is_valid(record: RawFileRecord) -> bool:
    """Return whether a cached raw-file ledger record matches its local file."""
    if record.local_path is None or record.sha256 is None:
        return False
    return local_file_matches(
        Path(record.local_path),
        sha256=record.sha256,
        downloaded_size=record.downloaded_size,
    )


def local_file_matches(
    path: Path,
    *,
    sha256: str,
    downloaded_size: int | None,
) -> bool:
    """Return whether a local raw cache file matches expected metadata."""
    if not path.exists() or not path.is_file():
        return False
    if downloaded_size is not None and path.stat().st_size != downloaded_size:
        return False
    return sha256_file(path) == sha256
