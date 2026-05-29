from __future__ import annotations

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("ingest.sources.everef")


class EverefSnapshotClient:
    """Small HTTP client with retry/backoff for everef.net listing pages."""

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

    def fetch_text(self, url: str) -> str:
        """GET *url* with retry, raise on 4xx/5xx, return response text."""
        logger.debug("Fetching url=%s", url)
        resp = self._session.get(url, timeout=self.timeout_seconds)
        resp.raise_for_status()
        return resp.text
