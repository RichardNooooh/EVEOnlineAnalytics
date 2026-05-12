from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from conftest import FakeResponse
from ingest.raw_files.downloader import download_with_sha256, sha256_file


class DownloadHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, bool]] = []

    def get(self, url: str, *, stream: bool) -> FakeResponse:
        self.calls.append((url, stream))
        return self.response


def test_sha256_file_hashes_file_contents(tmp_path: Path) -> None:
    path = tmp_path / "file.bin"
    path.write_bytes(b"abcdef")

    assert sha256_file(path, chunk_size=2) == hashlib.sha256(b"abcdef").hexdigest()


def test_download_with_sha256_streams_file_and_returns_digest_and_size(
    tmp_path: Path,
) -> None:
    response = FakeResponse(200, chunks=[b"abc", b"", b"def"])
    client = DownloadHttpClient(response)
    temp_path = tmp_path / "nested" / "file.bin"

    result = download_with_sha256(
        "https://example.test/file.bin",
        temp_path,
        http_client=client,
        chunk_size=2,
    )

    assert client.calls == [("https://example.test/file.bin", True)]
    assert temp_path.read_bytes() == b"abcdef"
    assert result.sha256 == hashlib.sha256(b"abcdef").hexdigest()
    assert result.downloaded_size == 6
    assert response.closed is True


def test_download_with_sha256_raises_on_http_error_status(tmp_path: Path) -> None:
    response = FakeResponse(500, chunks=[b"abc"])
    client = DownloadHttpClient(response)
    temp_path = tmp_path / "file.bin"

    with pytest.raises(
        RuntimeError, match="Unexpected Everef download status HTTP 500"
    ):
        download_with_sha256(
            "https://example.test/file.bin", temp_path, http_client=client
        )

    assert not temp_path.exists()
    assert response.closed is True
