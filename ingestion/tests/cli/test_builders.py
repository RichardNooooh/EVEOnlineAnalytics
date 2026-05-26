from __future__ import annotations

import pytest

from ingest.cli.builders import build_everef_market_history_config
from ingest.cli.parser import build_parser
from ingest.util import (
    DEFAULT_DATA_ROOT,
    DEFAULT_DUCKLAKE_CATALOG,
    DEFAULT_DUCKLAKE_METADATA_SCHEMA,
)


def test_market_history_maps_runtime_and_ducklake_flags() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "everef",
            "market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-31",
            "--data-root",
            "/data/runtime",
            "--raw-ledger-url",
            "postgresql://ledger",
            "--raw-max-copies-per-date",
            "5",
            "--ducklake-catalog",
            "postgresql://catalog",
            "--ducklake-metadata-schema",
            "custom_schema",
        ]
    )

    config = build_everef_market_history_config(args)

    assert config.start_date == "2025-01-01"
    assert config.end_date == "2025-01-31"
    assert config.data_root == "/data/runtime"
    assert config.raw_files.raw_root == "/data/runtime"
    assert config.raw_files.raw_ledger_url == "postgresql://ledger"
    assert config.raw_files.raw_max_copies_per_date == 5
    assert config.ducklake.ducklake_catalog == "postgresql://catalog"
    assert config.ducklake.ducklake_metadata_schema == "custom_schema"


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
    assert config.raw_files.raw_root == DEFAULT_DATA_ROOT
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
    ],
)
def test_market_history_validation_errors(argv: list[str], error_message: str) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    with pytest.raises(ValueError, match=error_message):
        build_everef_market_history_config(args)
