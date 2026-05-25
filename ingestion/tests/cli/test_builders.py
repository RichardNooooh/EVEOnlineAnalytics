from __future__ import annotations

import pytest

from ingest.cli.builders import build_everef_market_history_config
from ingest.cli.parser import build_parser


def test_market_history_maps_raw_and_ducklake_flags() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "everef",
            "market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-31",
            "--raw-root",
            "/data/raw",
            "--raw-ledger-url",
            "postgresql://ledger",
            "--raw-max-copies-per-date",
            "5",
            "--ducklake-name",
            "eve_market",
            "--ducklake-catalog",
            "postgresql://catalog",
            "--ducklake-storage",
            "s3://ducklake/files",
        ]
    )

    config = build_everef_market_history_config(args)

    assert config.date_range.start_date == "2025-01-01"
    assert config.date_range.end_date == "2025-01-31"
    assert config.raw_files.raw_root == "/data/raw"
    assert config.raw_files.raw_ledger_url == "postgresql://ledger"
    assert config.raw_files.raw_max_copies_per_date == 5
    assert config.ducklake.ducklake_name == "eve_market"
    assert config.ducklake.ducklake_catalog == "postgresql://catalog"
    assert config.ducklake.ducklake_storage == "s3://ducklake/files"


def test_market_history_rejects_invalid_start_date() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "everef",
            "market-history",
            "--start-date",
            "2025-13-01",
            "--end-date",
            "2025-01-31",
        ]
    )

    with pytest.raises(ValueError, match="start_date must be a valid YYYY-MM-DD date"):
        build_everef_market_history_config(args)


def test_market_history_rejects_descending_date_range() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "everef",
            "market-history",
            "--start-date",
            "2025-02-01",
            "--end-date",
            "2025-01-31",
        ]
    )

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        build_everef_market_history_config(args)


def test_market_history_rejects_negative_raw_copy_limit() -> None:
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
            "-1",
        ]
    )

    with pytest.raises(
        ValueError,
        match="raw_max_copies_per_date must be greater than or equal to 0",
    ):
        build_everef_market_history_config(args)
