from __future__ import annotations

from collections.abc import Iterable
from itertools import islice
import json
from pathlib import Path
from typing import TypeVar

import pytest

from ingest.raw_files.config import RawFilesConfig, sqlite_ledger_url
from ingest.raw_files.models import RawFileRecord

T = TypeVar("T")


class FakeHttpClient:
    def __init__(
        self,
        content: bytes,
        *,
        last_modified: str = "Wed, 01 Jan 2025 12:00:00 GMT",
        etag: str = '"etag-1"',
        totals: dict[str, int] | None = None,
    ) -> None:
        self.content = content
        self.last_modified = last_modified
        self.etag = etag
        self.totals = totals or {}
        self.head_calls: list[str] = []
        self.get_calls: list[str] = []

    def head(self, url: str, *, allow_redirects: bool) -> "FakeResponse":
        assert allow_redirects is True
        self.head_calls.append(url)
        return FakeResponse(
            200,
            headers={
                "content-length": str(len(self.content)),
                "last-modified": self.last_modified,
                "etag": self.etag,
            },
        )

    def get(self, url: str, *, stream: bool = False) -> "FakeResponse":
        self.get_calls.append(url)
        if url.endswith("/totals.json"):
            return FakeResponse(200, content=json.dumps(self.totals).encode())
        return FakeResponse(200, content=self.content)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self.chunks = chunks
        self.closed = False

    def iter_content(self, *, chunk_size: int):
        if self.chunks is not None:
            yield from self.chunks
            return
        yield self.content[:chunk_size]
        yield self.content[chunk_size:]

    def close(self) -> None:
        self.closed = True


class NoValidatorHttpClient(FakeHttpClient):
    def head(self, url: str, *, allow_redirects: bool) -> FakeResponse:
        assert allow_redirects is True
        self.head_calls.append(url)
        return FakeResponse(200)


def raw_files_config(tmp_path: Path, *, max_copies_per_date: int = 5) -> RawFilesConfig:
    return RawFilesConfig(
        raw_root=tmp_path / "raw",
        ledger_url=sqlite_ledger_url(tmp_path / "raw" / "raw_files.sqlite"),
        max_copies_per_date=max_copies_per_date,
    )


def raw_file_record(
    *,
    source_name: str = "source",
    dataset_name: str = "dataset",
    source_date: str = "2025-01-01",
    source_url: str = "https://example.test/file.csv.bz2",
    local_path: str | None = "/tmp/file.csv.bz2",
    sha256: str | None = "abc",
    content_length: int | None = 3,
    downloaded_size: int | None = 3,
    last_modified: str | None = "2025-01-01T12:00:00+00:00",
    etag: str | None = '"etag-1"',
    source_row_count: int | None = 3,
    first_seen_at: str = "2025-01-01T12:00:00+00:00",
    last_checked_at: str = "2025-01-01T12:00:00+00:00",
    downloaded_at: str | None = "2025-01-01T12:00:00+00:00",
    status: str = "downloaded",
    error_message: str | None = None,
) -> RawFileRecord:
    return RawFileRecord(
        id=None,
        source_name=source_name,
        dataset_name=dataset_name,
        source_date=source_date,
        source_url=source_url,
        local_path=local_path,
        sha256=sha256,
        content_length=content_length,
        downloaded_size=downloaded_size,
        last_modified=last_modified,
        etag=etag,
        source_row_count=source_row_count,
        first_seen_at=first_seen_at,
        last_checked_at=last_checked_at,
        downloaded_at=downloaded_at,
        status=status,
        error_message=error_message,
    )


def collect_bounded(values: Iterable[T], limit: int) -> list[T]:
    collected = list(islice(values, limit + 1))
    if len(collected) > limit:
        pytest.fail(f"expected at most {limit} values")
    return collected
