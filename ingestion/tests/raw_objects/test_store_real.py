"""Integration tests for RawObjectStore with real filesystem operations."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from eve_ingest.raw_objects import AcquisitionMode, RawObjectRequest, RawObjectStore, UpdateMode
from eve_ingest.raw_objects.http_models import ModifiedRead, ReadStatus, RevalidationMetadata
from eve_ingest.raw_objects.ledger import RawObjectLedger
from eve_ingest.raw_objects.ledger import repository as ledger_runtime


class FakeClient:
    def __init__(self, response: ModifiedRead) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str], str]] = []
        self.closed = False

    def read(
        self,
        *,
        source_url: str,
        request_headers: dict[str, str],
        temp_path: str,
    ):
        self.calls.append((source_url, request_headers, temp_path))
        Path(temp_path).parent.mkdir(parents=True, exist_ok=True)
        Path(temp_path).write_bytes(b"payload")
        return replace(self.response, temp_path=temp_path)

    def close(self) -> None:
        self.closed = True


def _make_ledger(monkeypatch) -> RawObjectLedger:
    monkeypatch.setattr(
        ledger_runtime,
        "create_engine",
        lambda _: __import__("sqlalchemy").create_engine("sqlite:///:memory:"),
    )
    monkeypatch.setattr(ledger_runtime, "normalize_ledger_url", lambda u: u)
    ledger = RawObjectLedger(ledger_url="sqlite:///:memory:")
    return ledger


def test_get_and_filter_unpublished_with_real_sqlite_ledger(monkeypatch, tmp_path: Path) -> None:
    ledger = _make_ledger(monkeypatch)
    client = FakeClient(
        ModifiedRead(
            status=ReadStatus.MODIFIED,
            fetched_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            temp_path=str(tmp_path / "download.tmp"),
            sha256="a" * 64,
            revalidation=RevalidationMetadata(etag='"etag-1"', content_length=7),
        )
    )
    request_obj = RawObjectRequest(
        source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
        identity_key={"source_date": "2026-01-01"},
    )

    with RawObjectStore(
        dataset_name="market-history",
        update_mode=UpdateMode.SNAPSHOT,
        raw_root=str(tmp_path / "raw"),
        client=client,  # ty: ignore[invalid-argument-type]
        ledger=ledger,
    ) as store:
        stored = store.get(request_obj)
        assert stored.changed is True

        all_results = store.get_many([request_obj], mode=AcquisitionMode.ALL)
        assert len(all_results) == 1
        assert all_results[0].path == stored.path

        unpublished = store.pubtrack.filter_unpublished(store.acquire_many([request_obj]))
        assert len(unpublished) == 1

        store.pubtrack.mark_published_many(unpublished)
        assert store.pubtrack.filter_unpublished(store.acquire_many([request_obj])) == []

    assert len(client.calls) == 1
