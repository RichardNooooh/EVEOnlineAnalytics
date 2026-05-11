"""Raw source-file acquisition models."""

from __future__ import annotations

from dataclasses import dataclass


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
    first_seen_at: str
    last_checked_at: str
    downloaded_at: str | None
    status: str
    error_message: str | None = None

    def to_source_item(self) -> dict[str, object]:
        """Return dlt source metadata for this cached file."""
        if self.local_path is None:
            msg = "raw file record has no local_path"
            raise ValueError(msg)

        return {
            "market_date": self.source_date,
            "url": self.source_url,
            "local_path": self.local_path,
            "sha256": self.sha256,
            "content_length": self.content_length,
            "last_modified": self.last_modified,
            "downloaded_at": self.downloaded_at,
        }
