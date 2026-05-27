"""HTTP client for streaming raw source files to temporary paths.

``HttpRawObjectClient`` wraps ``requests`` with retry logic, SHA-256 digest
computation, and conditional-request support so that the cache can download
new content or detect unchanged mutable objects.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ingest.cache.client_types import (
    ReadStatus,
    ReadResult,
    ModifiedRead,
    NotModifiedRead,
    RevalidationMetadata,
)

logger = logging.getLogger("ingest.cache")


class HttpRawObjectClient:
    """HTTP client for streaming raw source files to temporary paths.

    Example:
        ```python
        with HttpRawObjectClient(timeout_seconds=60) as client:
            result = client.read(
                source_url="https://example.com/file.csv.bz2",
                request_headers={},
                temp_path="/data/raw/.tmp/file.download",
            )
        ```
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        backoff_jitter: float = 0.25,
    ) -> None:
        """Create a new HTTP client.

        Args:
            timeout_seconds: Per-request socket timeout.
            max_retries: Maximum retry attempts for connection and read errors.
            backoff_factor: Exponential backoff multiplier between retries.
            backoff_jitter: Random jitter added to backoff delays.
        """
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.backoff_jitter = backoff_jitter
        self._session = self._build_session()

    def __enter__(self) -> HttpRawObjectClient:
        """Enter context manager.  Returns ``self``."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit context manager and close the HTTP session."""
        self.close()

    def read(
        self,
        *,
        source_url: str,
        request_headers: Mapping[str, str],
        temp_path: str,
    ) -> ReadResult:
        """Read one URL into ``temp_path``, returning status and source metadata.

        Pass conditional headers such as ``If-None-Match`` for mutable objects. A 304
        response returns ``ReadStatus.NOT_MODIFIED`` and does not create ``temp_path``.

        Args:
            source_url: Remote URL to fetch.
            request_headers: Extra headers sent with the request.  Typically
                empty for initial fetches or contains ``If-None-Match`` for
                revalidation.
            temp_path: Filesystem path where the response body is streamed.
                Parent directories are created automatically.

        Returns:
            ``NotModifiedRead`` on HTTP 304, otherwise ``ModifiedRead`` with
            the downloaded file path and SHA-256 digest.

        Raises:
            requests.HTTPError: When the server returns a 4xx/5xx status other
                than 304.
            OSError: When writing to ``temp_path`` fails.

        Example:
            ```python
            result = client.read(
                source_url=url,
                request_headers={"If-None-Match": '"etag-1"'},
                temp_path="/tmp/source.download",
            )
            if result.status is ReadStatus.MODIFIED:
                print(result.sha256)
            ```
        """

        temp_file = Path(temp_path)
        try:
            with self._session.get(
                source_url,
                headers=dict(request_headers),
                stream=True,
                timeout=self.timeout_seconds,
            ) as response:
                fetched_at = datetime.now(UTC)

                header_etag = response.headers.get("ETag")
                header_last_mod = response.headers.get("Last-Modified")
                header_content_length = _parse_content_length(response.headers.get("Content-Length"))

                if response.status_code == 304:
                    return NotModifiedRead(
                        status=ReadStatus.NOT_MODIFIED,
                        fetched_at=fetched_at,
                        revalidation=_build_revalidation(header_etag, header_last_mod, header_content_length),
                    )

                response.raise_for_status()
                temp_file.parent.mkdir(parents=True, exist_ok=True)

                content_length, sha256 = self._write_response_body(
                    response=response,
                    temp_file=temp_file,
                )
                if header_content_length and content_length != header_content_length:
                    logger.warning(
                        f"Header content length ({header_content_length}) "
                        + f"not equal to calculated content length ({content_length}). "
                        + f"url: {source_url}"
                    )

                return ModifiedRead(
                    status=ReadStatus.MODIFIED,
                    fetched_at=fetched_at,
                    temp_path=str(temp_file),
                    sha256=sha256,
                    revalidation=_build_revalidation(header_etag, header_last_mod, content_length),
                )
        except Exception:
            logger.exception("raw object read failed source_url=%s", source_url)
            if temp_file.exists():
                temp_file.unlink()
            raise

    def close(self) -> None:
        """Close the underlying HTTP session.

        Safe to call multiple times; subsequent calls are no-ops.
        """

        self._session.close()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=self.max_retries,
            read=self.max_retries,
            connect=self.max_retries,
            backoff_factor=self.backoff_factor,
            backoff_jitter=self.backoff_jitter,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        return session

    def _write_response_body(
        self,
        *,
        response: requests.Response,
        temp_file: Path,
    ) -> tuple[int, str]:
        digest = hashlib.sha256()
        content_length = 0
        with temp_file.open("wb") as stream:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                digest.update(chunk)
                stream.write(chunk)
                content_length += len(chunk)
        return content_length, digest.hexdigest()


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _build_revalidation(
    etag: str | None,
    last_modified: str | None,
    content_length: int | None,
) -> RevalidationMetadata:
    return RevalidationMetadata(
        etag=etag,
        last_modified=last_modified,
        content_length=content_length,
    )
