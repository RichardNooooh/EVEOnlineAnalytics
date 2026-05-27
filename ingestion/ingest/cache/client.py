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

from ingest.cache.models import FetchOutcome, FetchResult

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
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.backoff_jitter = backoff_jitter
        self._session = self._build_session()

    def __enter__(self) -> HttpRawObjectClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def read(
        self,
        *,
        source_url: str,
        request_headers: Mapping[str, str],
        temp_path: str,
    ) -> FetchResult:
        """Read one URL into `temp_path`, returning status and source metadata.

        Pass conditional headers such as `If-None-Match` for mutable objects. A 304
        response returns `FetchOutcome.NOT_MODIFIED` and does not create `temp_path`.

        Example:
            ```python
            result = client.read(
                source_url=url,
                request_headers={"If-None-Match": '"etag-1"'},
                temp_path="/tmp/source.download",
            )
            if result.outcome is FetchOutcome.DOWNLOADED:
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

                if response.status_code == 304:
                    return FetchResult(
                        outcome=FetchOutcome.NOT_MODIFIED,
                        fetched_at=fetched_at,
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                        content_length=_parse_content_length(
                            response.headers.get("Content-Length")
                        ),
                    )

                response.raise_for_status()
                temp_file.parent.mkdir(parents=True, exist_ok=True)

                content_length, sha256 = self._write_response_body(
                    response=response,
                    temp_file=temp_file,
                )

                return FetchResult(
                    outcome=FetchOutcome.DOWNLOADED,
                    fetched_at=fetched_at,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    content_length=content_length,
                    temp_path=str(temp_file),
                    sha256=sha256,
                )
        except Exception:
            logger.exception("raw object read failed source_url=%s", source_url)
            if temp_file.exists():
                temp_file.unlink()
            raise

    def close(self) -> None:
        """Close the underlying HTTP session.

        Example:
            ```python
            with HttpRawObjectClient() as client:
                ...
            ```
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
        session.mount("http://", adapter)
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
