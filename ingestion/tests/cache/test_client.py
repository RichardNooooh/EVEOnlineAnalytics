from __future__ import annotations

from pathlib import Path

import pytest

from ingest.cache.client import HttpRawObjectClient
from ingest.cache.models import FetchOutcome


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or []
        self._error = error
        self.closed = False

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def iter_content(self, chunk_size: int):
        del chunk_size
        for chunk in self._chunks:
            yield chunk
        if self._error is not None:
            raise self._error

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str], bool, float]] = []
        self.closed = False

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        stream: bool,
        timeout: float,
    ) -> FakeResponse:
        self.calls.append((url, headers, stream, timeout))
        return self.response

    def close(self) -> None:
        self.closed = True

    def mount(self, prefix: str, adapter) -> None:
        del prefix, adapter


def test_read_returns_not_modified_without_writing_file(
    monkeypatch, tmp_path: Path
) -> None:
    response = FakeResponse(
        status_code=304,
        headers={
            "ETag": '"etag-1"',
            "Last-Modified": "Wed, 27 May 2026 12:00:00 GMT",
            "Content-Length": "42",
        },
    )
    session = FakeSession(response)

    monkeypatch.setattr("ingest.cache.client.requests.Session", lambda: session)

    temp_path = tmp_path / "file.download"
    with HttpRawObjectClient(timeout_seconds=9.5) as client:
        result = client.read(
            source_url="https://example.com/file.csv",
            request_headers={"If-None-Match": '"etag-1"'},
            temp_path=str(temp_path),
        )

    assert result.outcome is FetchOutcome.NOT_MODIFIED
    assert result.revalidation.etag == '"etag-1"'
    assert result.revalidation.last_modified == "Wed, 27 May 2026 12:00:00 GMT"
    assert result.revalidation.content_length == 42
    assert temp_path.exists() is False
    assert response.closed is True
    assert session.calls == [
        (
            "https://example.com/file.csv",
            {"If-None-Match": '"etag-1"'},
            True,
            9.5,
        )
    ]


def test_read_streams_file_and_computes_sha256(monkeypatch, tmp_path: Path) -> None:
    response = FakeResponse(
        headers={"ETag": '"etag-2"'},
        chunks=[b"hello ", b"world"],
    )
    session = FakeSession(response)

    monkeypatch.setattr("ingest.cache.client.requests.Session", lambda: session)

    temp_path = tmp_path / "nested" / "file.download"
    with HttpRawObjectClient() as client:
        result = client.read(
            source_url="https://example.com/file.csv",
            request_headers={},
            temp_path=str(temp_path),
        )

    assert result.outcome is FetchOutcome.DOWNLOADED
    assert result.revalidation.content_length == 11
    assert result.sha256 == (
        "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    )
    assert temp_path.read_bytes() == b"hello world"
    assert response.closed is True


def test_read_removes_partial_file_when_stream_fails(
    monkeypatch, tmp_path: Path
) -> None:
    response = FakeResponse(chunks=[b"partial"], error=RuntimeError("boom"))
    session = FakeSession(response)

    monkeypatch.setattr("ingest.cache.client.requests.Session", lambda: session)

    temp_path = tmp_path / "file.download"
    with HttpRawObjectClient() as client:
        with pytest.raises(RuntimeError, match="boom"):
            client.read(
                source_url="https://example.com/file.csv",
                request_headers={},
                temp_path=str(temp_path),
            )

    assert temp_path.exists() is False
    assert response.closed is True
