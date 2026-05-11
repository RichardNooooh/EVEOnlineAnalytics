"""Download helpers for raw source files."""

from __future__ import annotations

import hashlib
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


@dataclass(frozen=True)
class DownloadResult:
    """Result of a streamed raw-file download."""

    sha256: str
    downloaded_size: int


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute sha256 for a local file."""
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_with_sha256(
    url: str,
    temp_path: Path,
    *,
    http_client: Any = requests,
    chunk_size: int = 1024 * 1024,
) -> DownloadResult:
    """Stream a URL to temp_path while computing sha256."""
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(http_client.get(url, stream=True)) as response:
        if response.status_code >= 400:
            msg = f"Unexpected Everef download status HTTP {response.status_code} for {url}"
            raise RuntimeError(msg)

        digest = hashlib.sha256()
        downloaded_size = 0
        with temp_path.open("wb") as file_obj:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                digest.update(chunk)
                downloaded_size += len(chunk)
                file_obj.write(chunk)

    return DownloadResult(sha256=digest.hexdigest(), downloaded_size=downloaded_size)
