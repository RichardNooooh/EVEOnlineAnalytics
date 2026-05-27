from __future__ import annotations

import pytest

from ingest.cli.builders import build_everef_market_history_config
from ingest.cli.parser import build_parser
from ingest.util import (
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

    config = build_everef_market_history_config(args)

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
                "--raw-max-copies-per-date",
                "-1",
            ],
            "raw_max_copies_per_date must be greater than or equal to 0",
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
        build_everef_market_history_config(args)


def test_market_history_zero_max_copies_normalizes_to_unlimited() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "everef",
            "market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-31",
            "--raw-max-copies-per-date",
            "0",
        ]
    )

    config = build_everef_market_history_config(args)

    assert config.raw_files.raw_max_copies_per_date is None
