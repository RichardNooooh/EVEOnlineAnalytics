from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from eve_ingest.raw_objects.http_client import build_retry_session

if TYPE_CHECKING:
    import requests

logger = logging.getLogger(__name__)


class EverefSnapshotClient:
    """Small HTTP client with retry/backoff for everef.net listing pages.

    Use as a context manager to guarantee the underlying connection pool is
    closed:

        with EverefSnapshotClient() as client:
            html = client.fetch_text(url)
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

    def __enter__(self) -> EverefSnapshotClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self._session.close()

    def _build_session(self) -> requests.Session:
        return build_retry_session(
            max_retries=self.max_retries,
            backoff_factor=self.backoff_factor,
            backoff_jitter=self.backoff_jitter,
        )

    def fetch_text(self, url: str) -> str:
        """GET *url* with retry, raise on 4xx/5xx, return response text."""
        logger.debug("Fetching url=%s", url)
        resp = self._session.get(url, timeout=self.timeout_seconds)
        resp.raise_for_status()
        return resp.text
