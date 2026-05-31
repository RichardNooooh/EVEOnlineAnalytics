from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from eve_ingest.cli.config_builders import build_everef_config
from eve_ingest.cli.parser import build_parser
from eve_ingest.logging_config import configure_logging
from eve_ingest.__main__ import main
from eve_ingest.util import (
    DEFAULT_DATA_ROOT,
    DEFAULT_DUCKLAKE_CATALOG,
    DEFAULT_DUCKLAKE_METADATA_SCHEMA,
    DEFAULT_RAW_LEDGER_URL,
    DEFAULT_RAW_ROOT,
)


def test_market_history_uses_runtime_defaults() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "everef",
            "market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-31",
        ]
    )

    config = build_everef_config(args)

    assert config.data_root == DEFAULT_DATA_ROOT
    assert config.raw_files.raw_root == DEFAULT_RAW_ROOT
    assert config.raw_files.raw_ledger_url == DEFAULT_RAW_LEDGER_URL
    assert config.ducklake.ducklake_catalog == DEFAULT_DUCKLAKE_CATALOG
    assert config.ducklake.ducklake_metadata_schema == DEFAULT_DUCKLAKE_METADATA_SCHEMA


@pytest.mark.parametrize(
    ("argv", "error_message"),
    [
        (
            [
                "everef",
                "market-history",
                "--start-date",
                "2025-13-01",
                "--end-date",
                "2025-01-31",
            ],
            "start_date must be a valid YYYY-MM-DD date",
        ),
        (
            [
                "everef",
                "market-history",
                "--start-date",
                "2025-02-01",
                "--end-date",
                "2025-01-31",
            ],
            "start_date must be on or before end_date",
        ),
        (
            [
                "everef",
                "market-history",
                "--start-date",
                "2025-01-01",
                "--end-date",
                "2025-01-31",
                "--raw-ledger-url",
                "sqlite:///:memory:",
            ],
            "raw_ledger_url must be a PostgreSQL URL",
        ),
    ],
)
def test_market_history_validation_errors(argv: list[str], error_message: str) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    with pytest.raises(ValueError, match=error_message):
        build_everef_config(args)


@pytest.mark.parametrize(
    ("argv", "expected_message"),
    [
        (
            [
                "everef",
                "market-history",
                "--start-date",
                "2025-01-01",
                "--end-date",
                "2025-01-31",
                "--raw-ledger-url",
                "",
            ],
            "raw_ledger_url must not be empty",
        ),
        (
            [
                "everef",
                "market-history",
                "--start-date",
                "2025-02-01",
                "--end-date",
                "2025-01-31",
            ],
            "start_date must be on or before end_date",
        ),
    ],
)
def test_main_surfaces_parser_and_validation_errors(
    monkeypatch,
    capsys,
    argv: list[str],
    expected_message: str,
) -> None:
    monkeypatch.setenv("INGEST_LOG_LEVEL", "CRITICAL")

    with pytest.raises(SystemExit) as exc_info:
        main(argv)

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert expected_message in captured.err


def test_main_propagates_non_zero_handler_return(monkeypatch) -> None:
    monkeypatch.setenv("INGEST_LOG_LEVEL", "CRITICAL")

    class _FakeParser:
        def parse_args(self, argv: list[str]):
            class _Args:
                @staticmethod
                def handler(args, parser) -> int:
                    return 1

            return _Args()

    monkeypatch.setattr("eve_ingest.__main__.build_parser", lambda: _FakeParser())

    assert main(["ignored"]) == 1


def test_main_logs_cli_dispatch(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr("eve_ingest.__main__.configure_logging", lambda: None)
    monkeypatch.setattr("eve_ingest.__main__.log_runtime_context", lambda: None)
    ingest_logger = logging.getLogger("eve_ingest")

    class _FakeParser:
        def parse_args(self, argv: list[str]):
            class _Args:
                command = "everef"
                sub_command = "market-history"
                pipeline_module = "eve_ingest.sources.everef.market_history"

                @staticmethod
                def handler(args, parser) -> int:
                    return 0

            return _Args()

    monkeypatch.setattr("eve_ingest.__main__.build_parser", lambda: _FakeParser())

    ingest_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="eve_ingest"):
            assert main(["ignored"]) == 0
    finally:
        ingest_logger.removeHandler(caplog.handler)

    assert (
        "cli_dispatch provider=everef subcommand=market-history pipeline_module=eve_ingest.sources.everef.market_history"
        in caplog.text
    )


def test_parser_logs_cli_run_start(caplog: pytest.LogCaptureFixture) -> None:
    ingest_logger = logging.getLogger("eve_ingest")
    parser = build_parser()
    args = parser.parse_args(
        [
            "everef",
            "market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-31",
        ]
    )

    ingest_logger.addHandler(caplog.handler)
    try:
        with patch("importlib.import_module") as import_module:
            import_module.return_value.run_pipeline.return_value = 0
            with caplog.at_level(logging.INFO, logger="eve_ingest"):
                assert args.handler(args, parser) == 0
    finally:
        ingest_logger.removeHandler(caplog.handler)

    assert (
        "cli_run_start provider=everef subcommand=market-history pipeline_module=eve_ingest.sources.everef.market_history"
        in caplog.text
    )
    assert "start_date=2025-01-01" in caplog.text
    assert "end_date=2025-01-31" in caplog.text
    assert f"data_root={DEFAULT_DATA_ROOT}" in caplog.text


def test_configure_logging_warns_on_invalid_env_level(monkeypatch, capsys) -> None:
    monkeypatch.setenv("INGEST_LOG_LEVEL", "banana")

    configure_logging(force=True)

    logging.getLogger("eve_ingest.test").info("info still logs")

    captured = capsys.readouterr()
    assert "Invalid INGEST_LOG_LEVEL='BANANA'; falling back to INFO" in captured.err
    assert captured.err.count("info still logs") == 1
