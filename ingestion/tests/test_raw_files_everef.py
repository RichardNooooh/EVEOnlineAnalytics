from __future__ import annotations

from pathlib import Path
import logging

import pytest

from conftest import FakeHttpClient, collect_bounded, raw_files_config
from ingest.raw_files.everef import (
    _market_history_source_item,
    acquire_everef_market_history_files,
    list_cached_everef_market_history_files,
)


def test_acquire_everef_uses_expected_url_and_metadata(tmp_path: Path) -> None:
    config = raw_files_config(tmp_path)
    client = FakeHttpClient(b"raw bytes", totals={"2025-01-01": 42})

    record = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
        check_headers=True,
    )[0]

    assert record.source_name == "everef"
    assert record.dataset_name == "market_history"
    assert record.source_date == "2025-01-01"
    assert (
        record.source_url
        == "https://example.test/history/2025/market-history-2025-01-01.csv.bz2"
    )
    assert client.head_calls == [record.source_url]
    assert client.get_calls == [
        "https://example.test/history/totals.json",
        record.source_url,
    ]
    assert record.etag == '"etag-1"'


def test_everef_cache_path_uses_compatible_layout(tmp_path: Path) -> None:
    record = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=raw_files_config(tmp_path),
        http_client=FakeHttpClient(b"raw bytes", totals={"2025-01-01": 42}),
        check_headers=True,
    )[0]

    assert record.local_path is not None
    assert (
        "/everef/market-history/year=2025/date=2025-01-01/sha256=" in record.local_path
    )
    assert record.local_path.endswith("/market-history-2025-01-01.csv.bz2")


def test_list_cached_everef_returns_source_item(tmp_path: Path) -> None:
    config = raw_files_config(tmp_path)
    record = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=FakeHttpClient(b"raw bytes", totals={"2025-01-01": 42}),
    )[0]

    cached_items = collect_bounded(
        list_cached_everef_market_history_files(
            "2025-01-01",
            "2025-01-01",
            base_url="https://example.test/history",
            config=config,
        ),
        1,
    )

    assert cached_items == [_market_history_source_item(record)]


def test_everef_source_item_returns_dlt_metadata(tmp_path: Path) -> None:
    record = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=raw_files_config(tmp_path),
        http_client=FakeHttpClient(b"raw bytes", totals={"2025-01-01": 42}),
        check_headers=True,
    )[0]

    assert _market_history_source_item(record) == {
        "market_date": "2025-01-01",
        "url": "https://example.test/history/2025/market-history-2025-01-01.csv.bz2",
        "local_path": record.local_path,
        "sha256": record.sha256,
        "content_length": 9,
        "last_modified": "2025-01-01T12:00:00+00:00",
        "downloaded_at": record.downloaded_at,
    }


def test_acquire_everef_totals_only_skips_unchanged_file(tmp_path: Path) -> None:
    config = raw_files_config(tmp_path)
    client = FakeHttpClient(b"raw bytes", totals={"2025-01-01": 42})

    first = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
    )[0]
    second = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
    )[0]

    assert first.local_path == second.local_path
    assert client.head_calls == []
    assert client.get_calls == [
        "https://example.test/history/totals.json",
        "https://example.test/history/2025/market-history-2025-01-01.csv.bz2",
        "https://example.test/history/totals.json",
    ]


def test_acquire_everef_warns_on_same_total_content_change(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config = raw_files_config(tmp_path)
    client = FakeHttpClient(
        b"raw bytes",
        etag='"etag-1"',
        totals={"2025-01-01": 42},
    )
    acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
        check_headers=True,
    )

    client.content = b"changed!!"
    client.etag = '"etag-2"'
    with caplog.at_level(logging.WARNING):
        acquire_everef_market_history_files(
            "2025-01-01",
            "2025-01-01",
            base_url="https://example.test/history",
            config=config,
            http_client=client,
            check_headers=True,
        )

    assert "unchanged totals.json count" in caplog.text


def test_list_cached_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not cached"):
        collect_bounded(
            list_cached_everef_market_history_files(
                "2025-01-01",
                "2025-01-01",
                base_url="https://example.test/history",
                config=raw_files_config(tmp_path),
            ),
            1,
        )
