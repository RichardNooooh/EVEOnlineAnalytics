from __future__ import annotations

import logging

import pytest

from eve_ingest.sources.everef.provenance import parse_last_modified_timestamp


def test_parse_last_modified_timestamp_supports_iso_and_http_date() -> None:
    iso_value = parse_last_modified_timestamp("2026-01-02T11:01:55Z")
    http_value = parse_last_modified_timestamp("Fri, 02 Jan 2026 11:01:55 GMT")

    assert iso_value == http_value


def test_parse_last_modified_timestamp_returns_none_for_invalid_value(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("eve_ingest.sources.everef")
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=logger.name):
            value = parse_last_modified_timestamp("not-a-timestamp")
            assert value is None
            assert "Could not parse last_modified timestamp" in caplog.text
    finally:
        logger.removeHandler(caplog.handler)
