from __future__ import annotations

import logging
from ingest.logging import configure_logging


def test_configure_logging_warns_on_invalid_env_level(monkeypatch, capsys) -> None:
    monkeypatch.setenv("INGEST_LOG_LEVEL", "banana")

    configure_logging(force=True)

    logging.getLogger("ingest.test").info("info still logs")

    captured = capsys.readouterr()
    assert "Invalid INGEST_LOG_LEVEL='BANANA'; falling back to INFO" in captured.err
    assert "info still logs" in captured.err
