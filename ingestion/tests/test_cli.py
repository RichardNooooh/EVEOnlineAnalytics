from __future__ import annotations

from ingest.cli import (
    build_everef_market_history_config,
    build_raw_files_sync_config,
)
from ingest.cli_config import (
    DateRangeCliConfig,
    EverefMarketHistoryCliConfig,
    RawFilesCliConfig,
    StorageCliConfig,
)
from ingest.input_sources import RAW_CACHE_INPUT_SOURCE, URL_INPUT_SOURCE


def test_cli_defaults_to_parquet_loader_format() -> None:
    parser = cli_parser()

    args = parser.parse_args(
        [
            "everef-market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-01",
        ]
    )

    assert args.data_root is None

    config = build_everef_market_history_config(args)

    assert config.loader_file_format == "parquet"
    assert config.destination == "ducklake"
    assert config.storage.storage_target == "local"
    assert config.input_source == RAW_CACHE_INPUT_SOURCE


def test_build_everef_market_history_config_maps_args() -> None:
    parser = cli_parser()

    args = parser.parse_args(
        [
            "everef-market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-02",
            "--base-url",
            "https://example.test/history",
            "--storage-target",
            "mounted",
            "--data-root",
            "/mnt/eve-market",
            "--ducklake-name",
            "arg_lake",
            "--ducklake-catalog",
            "postgresql://arg/catalog",
            "--ducklake-storage",
            "file:///mnt/arg",
            "--input-source",
            URL_INPUT_SOURCE,
            "--sync-raw",
            "--raw-root",
            "/tmp/raw",
            "--raw-max-copies-per-date",
            "9",
        ]
    )

    config = build_everef_market_history_config(args)

    assert config == EverefMarketHistoryCliConfig(
        date_range=DateRangeCliConfig("2025-01-01", "2025-01-02"),
        storage=StorageCliConfig(
            storage_target="mounted",
            data_root="/mnt/eve-market",
        ),
        base_url="https://example.test/history",
        ducklake_name="arg_lake",
        ducklake_catalog="postgresql://arg/catalog",
        ducklake_storage="file:///mnt/arg",
        input_source=URL_INPUT_SOURCE,
        sync_raw=True,
        raw_files=RawFilesCliConfig(
            raw_root="/tmp/raw",
            raw_max_copies_per_date="9",
        ),
    )


def test_build_raw_files_sync_config_maps_args() -> None:
    parser = cli_parser()

    args = parser.parse_args(
        [
            "raw-files",
            "sync-everef-market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-02",
            "--storage-target",
            "mounted",
            "--data-root",
            "/mnt/eve-market",
            "--raw-root",
            "/tmp/raw",
            "--raw-ledger-url",
            "postgresql://ledger.test/raw",
            "--raw-max-copies-per-date",
            "0",
        ]
    )

    assert args.command == "raw-files"
    assert args.raw_command == "sync-everef-market-history"

    config = build_raw_files_sync_config(args)

    assert config.date_range.start_date == "2025-01-01"
    assert config.date_range.end_date == "2025-01-02"
    assert config.storage.storage_target == "mounted"
    assert config.storage.data_root == "/mnt/eve-market"
    assert config.raw_files.raw_root == "/tmp/raw"
    assert config.raw_files.raw_ledger_url == "postgresql://ledger.test/raw"
    assert config.raw_files.raw_max_copies_per_date == "0"


def cli_parser():
    from ingest.cli import build_parser

    return build_parser()
