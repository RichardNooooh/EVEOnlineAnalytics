from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from itertools import islice
from pathlib import Path
from typing import TypeVar

import pandas as pd
import pyarrow as pa
import pytest

from ingest.clients import everef as client
from ingest.contracts.market_history import (
    MARKET_HISTORY_COLUMNS,
    MARKET_HISTORY_PRIMARY_KEY,
)
from ingest.sources import everef as source

T = TypeVar("T")


class FakeProbeClient:
    def __init__(self, response=None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.calls: list[tuple[str, bool]] = []

    def head(self, url: str, *, allow_redirects: bool) -> FakeResponse:
        self.calls.append((url, allow_redirects))
        if self.exc is not None:
            raise self.exc
        return self.response


class FakeResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


def test_list_market_history_urls_emits_market_date_and_url() -> None:
    urls = list(
        client.iter_market_history_url_items(
            date(2025, 1, 1), date(2025, 1, 2), "https://example.test/history"
        )
    )

    assert urls == [
        {
            "market_date": "2025-01-01",
            "url": "https://example.test/history/2025/market-history-2025-01-01.csv.bz2",
        },
        {
            "market_date": "2025-01-02",
            "url": "https://example.test/history/2025/market-history-2025-01-02.csv.bz2",
        },
    ]


def test_probe_market_history_file_yields_enriched_item() -> None:
    fake_client = FakeProbeClient(
        FakeResponse(
            200,
            {
                "content-length": "123",
                "last-modified": "Wed, 01 Jan 2025 12:00:00 GMT",
                "etag": '"etag-1"',
            },
        )
    )
    item = {"market_date": "2025-01-01", "url": "https://example.test/file.csv.bz2"}

    assert client.probe_market_history_file_item(
        item,
        http_client=fake_client,
        logger=source.logger,
        request_exception_type=source.requests.RequestException,
    ) == {
        "market_date": "2025-01-01",
        "url": "https://example.test/file.csv.bz2",
        "content_length": 123,
        "last_modified": "2025-01-01T12:00:00+00:00",
        "etag": '"etag-1"',
    }
    assert fake_client.calls == [("https://example.test/file.csv.bz2", True)]
    assert item == {
        "market_date": "2025-01-01",
        "url": "https://example.test/file.csv.bz2",
    }


def test_probe_market_history_file_skips_404() -> None:
    assert (
        client.probe_market_history_file_item(
            _probe_item(),
            http_client=FakeProbeClient(FakeResponse(404)),
            logger=source.logger,
            request_exception_type=source.requests.RequestException,
        )
        is None
    )


def test_probe_market_history_file_raises_on_unexpected_status() -> None:
    with pytest.raises(RuntimeError, match="Unexpected Everef status HTTP 500"):
        client.probe_market_history_file_item(
            _probe_item(),
            http_client=FakeProbeClient(FakeResponse(500)),
            logger=source.logger,
            request_exception_type=source.requests.RequestException,
        )


def test_probe_market_history_file_raises_on_request_exception() -> None:
    with pytest.raises(RuntimeError, match="Everef probe failed"):
        client.probe_market_history_file_item(
            _probe_item(),
            http_client=FakeProbeClient(
                exc=source.requests.RequestException("timeout")
            ),
            logger=source.logger,
            request_exception_type=source.requests.RequestException,
        )


def test_read_market_history_csv_yields_chunks_with_source_metadata(
    tmp_path: Path,
) -> None:
    csv_path = _write_market_history_fixture(tmp_path, _valid_market_history_frame())
    item = {
        "market_date": "2025-01-01",
        "url": str(csv_path),
        "content_length": 123,
        "last_modified": "2025-01-01T12:00:00+00:00",
    }

    chunks = _collect_bounded(
        source.read_market_history_csv.__wrapped__(item, chunksize=1), 2
    )

    assert len(chunks) == 2
    assert all(isinstance(chunk, pa.Table) for chunk in chunks)
    first_chunk = chunks[0].to_pandas()
    second_chunk = chunks[1].to_pandas()
    assert list(first_chunk["_source_market_date"]) == ["2025-01-01"]
    assert list(first_chunk["_source_url"]) == [str(csv_path)]
    assert list(first_chunk["_source_content_length"]) == [123]
    assert list(first_chunk["_source_last_modified"]) == ["2025-01-01T12:00:00+00:00"]
    assert first_chunk["_ingested_at"].iloc[0] == second_chunk["_ingested_at"].iloc[0]
    assert chunks[0].schema.field("date").nullable is False
    assert chunks[0].schema.field("region_id").nullable is False
    assert chunks[0].schema.field("type_id").nullable is False


def test_read_market_history_csv_reads_local_path_and_preserves_source_url(
    tmp_path: Path,
) -> None:
    csv_path = _write_market_history_fixture(tmp_path, _valid_market_history_frame())
    item = {
        "market_date": "2025-01-01",
        "url": "https://example.test/history/2025/market-history-2025-01-01.csv.bz2",
        "local_path": str(csv_path),
        "sha256": "abc123",
        "downloaded_at": "2025-01-01T12:00:00+00:00",
    }

    chunks = _collect_bounded(
        source.read_market_history_csv.__wrapped__(item, chunksize=10), 1
    )

    assert len(chunks) == 1
    chunk = chunks[0].to_pandas()
    assert list(chunk["_source_url"]) == [item["url"], item["url"]]
    assert list(chunk["_source_local_path"]) == [str(csv_path), str(csv_path)]
    assert list(chunk["_source_sha256"]) == ["abc123", "abc123"]
    assert list(chunk["_source_downloaded_at"]) == [
        "2025-01-01T12:00:00+00:00",
        "2025-01-01T12:00:00+00:00",
    ]


def test_market_history_contract_declares_publication_keys() -> None:
    assert MARKET_HISTORY_PRIMARY_KEY == ["date", "region_id", "type_id"]
    assert set(MARKET_HISTORY_PRIMARY_KEY).issubset(MARKET_HISTORY_COLUMNS)
    assert all(
        MARKET_HISTORY_COLUMNS[column_name]["nullable"] is False
        for column_name in MARKET_HISTORY_PRIMARY_KEY
    )


def test_read_market_history_csv_rejects_non_positive_chunksize(tmp_path: Path) -> None:
    csv_path = _write_market_history_fixture(tmp_path, _valid_market_history_frame())

    with pytest.raises(ValueError, match="chunksize must be greater than 0"):
        _collect_bounded(
            source.read_market_history_csv.__wrapped__(
                _read_item(csv_path), chunksize=0
            ),
            1,
        )


def test_read_market_history_csv_raises_on_missing_required_column(
    tmp_path: Path,
) -> None:
    frame = _valid_market_history_frame().drop(columns=["volume"])
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(ValueError, match="missing columns: volume"):
        _collect_bounded(
            source.read_market_history_csv.__wrapped__(
                _read_item(csv_path), chunksize=10
            ),
            1,
        )


def test_read_market_history_csv_raises_on_null_primary_key(tmp_path: Path) -> None:
    frame = _valid_market_history_frame()
    frame.loc[0, "type_id"] = None
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(ValueError, match="null primary-key"):
        _collect_bounded(
            source.read_market_history_csv.__wrapped__(
                _read_item(csv_path), chunksize=10
            ),
            1,
        )


def test_read_market_history_csv_raises_on_duplicate_primary_key(
    tmp_path: Path,
) -> None:
    frame = pd.concat(
        [
            _valid_market_history_frame().iloc[[0]],
            _valid_market_history_frame().iloc[[0]],
        ],
        ignore_index=True,
    )
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(ValueError, match="duplicate primary-key"):
        _collect_bounded(
            source.read_market_history_csv.__wrapped__(
                _read_item(csv_path), chunksize=10
            ),
            1,
        )


def test_read_market_history_csv_raises_on_duplicate_primary_key_across_chunks(
    tmp_path: Path,
) -> None:
    frame = pd.concat(
        [_valid_market_history_frame(), _valid_market_history_frame().iloc[[0]]],
        ignore_index=True,
    )
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(ValueError, match="duplicate .*region_id, type_id"):
        _collect_bounded(
            source.read_market_history_csv.__wrapped__(
                _read_item(csv_path), chunksize=2
            ),
            2,
        )


def test_read_market_history_csv_raises_on_date_mismatch(tmp_path: Path) -> None:
    frame = _valid_market_history_frame()
    frame.loc[0, "date"] = "2025-01-02"
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(ValueError, match="do not match source market_date"):
        _collect_bounded(
            source.read_market_history_csv.__wrapped__(
                _read_item(csv_path), chunksize=10
            ),
            1,
        )


def test_read_market_history_csv_raises_on_later_chunk_date_mismatch(
    tmp_path: Path,
) -> None:
    frame = _valid_market_history_frame()
    frame.loc[1, "date"] = "2025-01-02"
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(ValueError, match="do not match source market_date"):
        _collect_bounded(
            source.read_market_history_csv.__wrapped__(
                _read_item(csv_path), chunksize=1
            ),
            2,
        )


def test_read_market_history_csv_raises_on_negative_numeric_value(
    tmp_path: Path,
) -> None:
    frame = _valid_market_history_frame()
    frame.loc[0, "volume"] = -1
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(ValueError, match="negative numeric"):
        _collect_bounded(
            source.read_market_history_csv.__wrapped__(
                _read_item(csv_path), chunksize=10
            ),
            1,
        )


def test_read_market_history_csv_raises_on_read_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_read_csv(*args, **kwargs):
        raise OSError("cannot read")

    monkeypatch.setattr(source.pd, "read_csv", fail_read_csv)

    with pytest.raises(RuntimeError, match="Could not read Everef CSV"):
        _collect_bounded(
            source.read_market_history_csv.__wrapped__(
                _read_item(Path("missing.csv.bz2"))
            ),
            1,
        )


def _collect_bounded(values: Iterable[T], limit: int) -> list[T]:
    collected = list(islice(values, limit + 1))
    if len(collected) > limit:
        pytest.fail(f"expected at most {limit} values")
    return collected


def _probe_item() -> dict[str, str]:
    return {"market_date": "2025-01-01", "url": "https://example.test/file.csv.bz2"}


def _read_item(csv_path: Path) -> dict[str, str]:
    return {"market_date": "2025-01-01", "url": str(csv_path)}


def _valid_market_history_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2025-01-01",
                "region_id": 10000002,
                "type_id": 34,
                "average": 5.25,
                "highest": 5.27,
                "lowest": 5.11,
                "order_count": 2267,
                "volume": 16276782035,
            },
            {
                "date": "2025-01-01",
                "region_id": 10000002,
                "type_id": 35,
                "average": 10.25,
                "highest": 10.27,
                "lowest": 10.11,
                "order_count": 123,
                "volume": 456,
            },
        ]
    )


def _write_market_history_fixture(tmp_path: Path, frame: pd.DataFrame) -> Path:
    csv_path = tmp_path / "market-history-2025-01-01.csv.bz2"
    frame.to_csv(csv_path, index=False, compression="bz2")
    return csv_path
