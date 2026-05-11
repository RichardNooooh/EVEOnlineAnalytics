from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from eve_market_ingestion.sources import everef_market_history as source


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
        source.list_market_history_urls._pipe.gen(
            date(2025, 1, 1),
            date(2025, 1, 2),
            "https://example.test/history",
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


def test_probe_market_history_file_yields_enriched_item(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeProbeClient(
        FakeResponse(
            200,
            {
                "content-length": "123",
                "last-modified": "Wed, 01 Jan 2025 12:00:00 GMT",
            },
        )
    )
    monkeypatch.setattr(source, "_PROBE_CLIENT", fake_client)
    item = {"market_date": "2025-01-01", "url": "https://example.test/file.csv.bz2"}

    assert list(source._probe_market_history_file(item)) == [
        {
            "market_date": "2025-01-01",
            "url": "https://example.test/file.csv.bz2",
            "content_length": 123,
            "last_modified": "2025-01-01T12:00:00+00:00",
        }
    ]
    assert fake_client.calls == [("https://example.test/file.csv.bz2", True)]
    assert item == {"market_date": "2025-01-01", "url": "https://example.test/file.csv.bz2"}


def test_probe_market_history_file_skips_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(source, "_PROBE_CLIENT", FakeProbeClient(FakeResponse(404)))

    assert list(source._probe_market_history_file(_probe_item())) == []


def test_probe_market_history_file_raises_on_unexpected_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source, "_PROBE_CLIENT", FakeProbeClient(FakeResponse(500)))

    with pytest.raises(RuntimeError, match="Unexpected Everef status HTTP 500"):
        list(source._probe_market_history_file(_probe_item()))


def test_probe_market_history_file_raises_on_request_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        source,
        "_PROBE_CLIENT",
        FakeProbeClient(exc=source.requests.RequestException("timeout")),
    )

    with pytest.raises(RuntimeError, match="Everef probe failed"):
        list(source._probe_market_history_file(_probe_item()))


def test_read_market_history_csv_yields_chunks_with_source_metadata(tmp_path: Path) -> None:
    csv_path = _write_market_history_fixture(tmp_path, _valid_market_history_frame())
    item = {
        "market_date": "2025-01-01",
        "url": str(csv_path),
        "content_length": 123,
        "last_modified": "2025-01-01T12:00:00+00:00",
    }

    chunks = list(source._read_market_history_csv(item, chunksize=1))

    assert len(chunks) == 2
    assert list(chunks[0]["_source_market_date"]) == ["2025-01-01"]
    assert list(chunks[0]["_source_url"]) == [str(csv_path)]
    assert list(chunks[0]["_source_content_length"]) == [123]
    assert list(chunks[0]["_source_last_modified"]) == ["2025-01-01T12:00:00+00:00"]
    assert chunks[0]["_ingested_at"].iloc[0] == chunks[1]["_ingested_at"].iloc[0]


def test_read_market_history_csv_uses_ducklake_merge_hints() -> None:
    table_schema = source.read_market_history_csv.compute_table_schema()

    assert table_schema["write_disposition"] == "merge"
    assert table_schema["x-merge-strategy"] == "delete-insert"
    assert table_schema["columns"]["date"]["merge_key"] is True
    assert table_schema["columns"]["date"]["primary_key"] is True
    assert table_schema["columns"]["region_id"]["primary_key"] is True
    assert table_schema["columns"]["type_id"]["primary_key"] is True


def test_read_market_history_csv_rejects_non_positive_chunksize(tmp_path: Path) -> None:
    csv_path = _write_market_history_fixture(tmp_path, _valid_market_history_frame())

    with pytest.raises(ValueError, match="chunksize must be greater than 0"):
        list(source._read_market_history_csv(_read_item(csv_path), chunksize=0))


def test_read_market_history_csv_raises_on_missing_required_column(tmp_path: Path) -> None:
    frame = _valid_market_history_frame().drop(columns=["volume"])
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(RuntimeError, match="missing columns: volume"):
        list(source._read_market_history_csv(_read_item(csv_path), chunksize=10))


def test_read_market_history_csv_raises_on_null_primary_key(tmp_path: Path) -> None:
    frame = _valid_market_history_frame()
    frame.loc[0, "type_id"] = None
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(RuntimeError, match="null primary-key"):
        list(source._read_market_history_csv(_read_item(csv_path), chunksize=10))


def test_read_market_history_csv_raises_on_duplicate_primary_key(tmp_path: Path) -> None:
    frame = pd.concat(
        [_valid_market_history_frame().iloc[[0]], _valid_market_history_frame().iloc[[0]]],
        ignore_index=True,
    )
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(RuntimeError, match="duplicate primary-key"):
        list(source._read_market_history_csv(_read_item(csv_path), chunksize=10))


def test_read_market_history_csv_raises_on_duplicate_primary_key_across_chunks(
    tmp_path: Path,
) -> None:
    frame = pd.concat(
        [_valid_market_history_frame(), _valid_market_history_frame().iloc[[0]]],
        ignore_index=True,
    )
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(RuntimeError, match="duplicate primary-key rows across chunks"):
        list(source._read_market_history_csv(_read_item(csv_path), chunksize=2))


def test_read_market_history_csv_raises_on_date_mismatch(tmp_path: Path) -> None:
    frame = _valid_market_history_frame()
    frame.loc[0, "date"] = "2025-01-02"
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(RuntimeError, match="do not match source market_date"):
        list(source._read_market_history_csv(_read_item(csv_path), chunksize=10))


def test_read_market_history_csv_raises_on_negative_numeric_value(tmp_path: Path) -> None:
    frame = _valid_market_history_frame()
    frame.loc[0, "volume"] = -1
    csv_path = _write_market_history_fixture(tmp_path, frame)

    with pytest.raises(RuntimeError, match="negative numeric"):
        list(source._read_market_history_csv(_read_item(csv_path), chunksize=10))


def test_read_market_history_csv_raises_on_read_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_read_csv(*args, **kwargs):
        raise OSError("cannot read")

    monkeypatch.setattr(source.pd, "read_csv", fail_read_csv)

    with pytest.raises(RuntimeError, match="Could not read Everef CSV"):
        list(source._read_market_history_csv(_read_item(Path("missing.csv.bz2"))))


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
