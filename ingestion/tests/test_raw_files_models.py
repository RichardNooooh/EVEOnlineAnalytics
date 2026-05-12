from __future__ import annotations

import pytest

from conftest import raw_file_record


def test_raw_file_record_to_source_item_returns_dlt_metadata() -> None:
    record = raw_file_record()

    assert record.to_source_item() == {
        "market_date": "2025-01-01",
        "url": "https://example.test/file.csv.bz2",
        "local_path": "/tmp/file.csv.bz2",
        "sha256": "abc",
        "content_length": 3,
        "last_modified": "2025-01-01T12:00:00+00:00",
        "downloaded_at": "2025-01-01T12:00:00+00:00",
    }


def test_raw_file_record_to_source_item_rejects_missing_local_path() -> None:
    with pytest.raises(ValueError, match="raw file record has no local_path"):
        raw_file_record(local_path=None).to_source_item()
