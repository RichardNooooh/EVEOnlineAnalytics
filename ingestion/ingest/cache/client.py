from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Mapping

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ingest.cache.models import ClientReadResult, ReadOutcome

logger = logging.getLogger("ingest.cache")


@dataclass(frozen=True)
class HttpRawObjectClient:
    """HTTP client for streaming raw source files to temporary paths.

    Example:
        ```python
        client = HttpRawObjectClient(timeout_seconds=60)
        result = client.read(
            source_url="https://example.com/file.csv.bz2",
            request_headers={},
            temp_path="/data/raw/.tmp/file.download",
        )
        client.close()
        ```
    """

    timeout_seconds: float = 30.0
    max_retries: int = 3
    backoff_factor: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(self, "_session", self._build_session())

    def read(
        self,
        *,
        source_url: str,
        request_headers: Mapping[str, str],
        temp_path: str,
    ) -> ClientReadResult:
        """Read one URL into `temp_path`, returning status and source metadata.

        Pass conditional headers such as `If-None-Match` for mutable objects. A 304
        response returns `ReadOutcome.NOT_MODIFIED` and does not create `temp_path`.

        Example:
            ```python
            result = client.read(
                source_url=url,
                request_headers={"If-None-Match": '"etag-1"'},
                temp_path="/tmp/source.download",
            )
            if result.outcome is ReadOutcome.DOWNLOADED:
                print(result.sha256)
            ```
        """

        response = None
        temp_file = Path(temp_path)
        try:
            response = self._session.get(
                source_url,
                headers=dict(request_headers),
                stream=True,
                timeout=self.timeout_seconds,
            )
            fetched_at = datetime.now(UTC)

            if response.status_code == 304:
                return ClientReadResult(
                    outcome=ReadOutcome.NOT_MODIFIED,
                    fetched_at=fetched_at,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    content_length=_parse_content_length(
                        response.headers.get("Content-Length")
                    ),
                )

            response.raise_for_status()
            temp_file.parent.mkdir(parents=True, exist_ok=True)

            digest = hashlib.sha256()
            content_length = 0
            with temp_file.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    digest.update(chunk)
                    stream.write(chunk)
                    content_length += len(chunk)

            return ClientReadResult(
                outcome=ReadOutcome.DOWNLOADED,
                fetched_at=fetched_at,
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
                content_length=content_length,
                temp_path=str(temp_file),
                sha256=digest.hexdigest(),
            )
        except Exception:
            logger.exception("raw object read failed source_url=%s", source_url)
            if temp_file.exists():
                temp_file.unlink()
            raise
        finally:
            if response is not None:
                response.close()

    def close(self) -> None:
        """Close the underlying HTTP session.

        Example:
            ```python
            client = HttpRawObjectClient()
            try:
                ...
            finally:
                client.close()
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
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
