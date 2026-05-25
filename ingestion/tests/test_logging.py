from __future__ import annotations

import logging
from ingest.logging import configure_logging, log_runtime_context


def test_configure_logging_uses_plain_log_lines(monkeypatch, capsys) -> None:
    monkeypatch.setenv("INGEST_LOG_LEVEL", "INFO")

    configure_logging(force=True)

    logging.getLogger("ingest.test").info("sync complete")

    captured = capsys.readouterr()
    assert "[INFO|ingest.test]" in captured.err
    assert "sync complete" in captured.err


def test_log_runtime_context_writes_single_startup_line(monkeypatch, capsys) -> None:
    monkeypatch.setenv("INGEST_LOG_LEVEL", "INFO")
    monkeypatch.setenv("AIRFLOW_CTX_DAG_ID", "ingest-dag")
    monkeypatch.setenv("AIRFLOW_CTX_TASK_ID", "everef-run")
    monkeypatch.setenv("AIRFLOW_CTX_RUN_ID", "scheduled__2026-05-25")
    monkeypatch.setenv("AIRFLOW_CTX_TRY_NUMBER", "2")

    configure_logging(force=True)

    log_runtime_context()
    logging.getLogger("ingest.test").info("sync complete")

    captured = capsys.readouterr()
    assert "runtime_context dag_id=ingest-dag task_id=everef-run" in captured.err
    assert "run_id=scheduled__2026-05-25 try_number=2" in captured.err
    assert "sync complete" in captured.err
    assert (
        "dag_id=ingest-dag task_id=everef-run run_id=scheduled__2026-05-25 try_number=2 sync complete"
        not in captured.err
    )


def test_configure_logging_warns_on_invalid_env_level(monkeypatch, capsys) -> None:
    monkeypatch.setenv("INGEST_LOG_LEVEL", "banana")

    configure_logging(force=True)

    logging.getLogger("ingest.test").info("info still logs")

    captured = capsys.readouterr()
    assert "Invalid INGEST_LOG_LEVEL='BANANA'; falling back to INFO" in captured.err
    assert "info still logs" in captured.err
