"""Command-line entrypoint for ingestion jobs."""

from __future__ import annotations

import argparse
import logging

from ingest.cli_config import (
    DateRangeCliConfig,
    EverefMarketHistoryCliConfig,
    RawFilesCliConfig,
    RawFilesSyncCliConfig,
    StorageCliConfig,
)
from ingest.input_sources import INPUT_SOURCES
from ingest.pipelines.everef import (
    run_everef_market_history_pipeline,
)
from ingest.publishers.ducklake import (
    DUCKLAKE_CATALOG_ENV_VAR,
    DUCKLAKE_NAME_ENV_VAR,
    DUCKLAKE_STORAGE_ENV_VAR,
)
from ingest.raw_files.config import (
    RAW_FILES_LEDGER_URL_ENV_VAR,
    RAW_FILES_MAX_COPIES_PER_DATE_ENV_VAR,
    RAW_FILES_ROOT_ENV_VAR,
)
from ingest.raw_files.everef import sync_everef_market_history_files
from ingest.storage_config import (
    DATA_ROOT_ENV_VAR,
    STORAGE_TARGETS,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EVE market ingestion jobs.")
    subparsers = parser.add_subparsers(dest="command")

    everef_parser = subparsers.add_parser(
        "everef-market-history",
        help="Ingest Everef daily market history CSV archives.",
    )

    build_everef_parser(everef_parser)

    raw_files_parser = subparsers.add_parser(
        "raw-files",
        help="Manage raw source-file acquisition caches.",
    )

    build_raw_files_parser(raw_files_parser)
    return parser


def add_date_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--start-date", required=True, help="Inclusive YYYY-MM-DD date."
    )
    parser.add_argument("--end-date", required=True, help="Inclusive YYYY-MM-DD date.")


def add_storage_args(parser: argparse.ArgumentParser, *, help_prefix: str) -> None:
    parser.add_argument(
        "--storage-target",
        choices=STORAGE_TARGETS,
        default=argparse.SUPPRESS,
        help=help_prefix,
    )
    parser.add_argument(
        "--data-root",
        default=None,
        help=(
            "Mounted storage root used with --storage-target mounted; "
            f"env fallback {DATA_ROOT_ENV_VAR}."
        ),
    )


def add_raw_file_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--raw-root",
        default=None,
        help=f"Raw source-file cache root. Overrides {RAW_FILES_ROOT_ENV_VAR}.",
    )
    parser.add_argument(
        "--raw-ledger-url",
        default=None,
        help=f"Raw source-file ledger URL. Overrides {RAW_FILES_LEDGER_URL_ENV_VAR}.",
    )
    parser.add_argument(
        "--raw-max-copies-per-date",
        default=None,
        help=(
            "Maximum raw file copies to keep per source date; 0 disables deletion. "
            f"Overrides {RAW_FILES_MAX_COPIES_PER_DATE_ENV_VAR}."
        ),
    )


def add_ducklake_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ducklake-name",
        default=None,
        help=(
            "DuckLake attach name. "
            f"Overrides {DUCKLAKE_NAME_ENV_VAR}, then defaults to eve_market."
        ),
    )
    parser.add_argument(
        "--ducklake-catalog",
        default=None,
        help=(
            "DuckLake catalog URL. "
            f"Overrides {DUCKLAKE_CATALOG_ENV_VAR}, then defaults to local sqlite."
        ),
    )
    parser.add_argument(
        "--ducklake-storage",
        default=None,
        help=(
            "DuckLake storage URL. "
            f"Overrides {DUCKLAKE_STORAGE_ENV_VAR}, then --storage-target defaults."
        ),
    )


def build_everef_parser(everef_parser: argparse.ArgumentParser) -> None:
    add_date_args(everef_parser)
    everef_parser.add_argument("--pipeline-name", default=argparse.SUPPRESS)
    everef_parser.add_argument("--dataset-name", default=argparse.SUPPRESS)
    everef_parser.add_argument("--destination", default=argparse.SUPPRESS)
    add_ducklake_args(everef_parser)
    add_storage_args(
        everef_parser,
        help_prefix=(
            "Default DuckLake storage target when --ducklake-storage "
            "and env override are unset."
        ),
    )
    everef_parser.add_argument("--base-url", default=None)
    everef_parser.add_argument("--chunksize", type=int, default=None)
    everef_parser.add_argument(
        "--check-headers",
        action="store_true",
        help="Use HTTP headers with totals.json when detecting changed Everef files.",
    )
    everef_parser.add_argument(
        "--input-source",
        choices=INPUT_SOURCES,
        default=argparse.SUPPRESS,
        help="Read CSVs from source URLs or from the raw-file cache.",
    )
    everef_parser.add_argument(
        "--sync-raw",
        action="store_true",
        help="Download raw files first, then load from the raw-file cache.",
    )
    add_raw_file_args(everef_parser)
    everef_parser.add_argument("--loader-file-format", default=argparse.SUPPRESS)
    everef_parser.add_argument("--dev-mode", action="store_true")


def build_raw_files_parser(raw_files_parser: argparse.ArgumentParser) -> None:
    raw_subparsers = raw_files_parser.add_subparsers(dest="raw_command")
    raw_subparsers.required = True
    raw_sync_parser = raw_subparsers.add_parser(
        "sync-everef-market-history",
        help="Download Everef market history CSV archives into the raw cache.",
    )
    add_date_args(raw_sync_parser)
    add_storage_args(
        raw_sync_parser,
        help_prefix=(
            "Default raw cache target when --raw-root and env override are unset."
        ),
    )
    raw_sync_parser.add_argument("--base-url", default=None)
    raw_sync_parser.add_argument(
        "--check-headers",
        action="store_true",
        help="Use HTTP headers with totals.json when detecting changed Everef files.",
    )
    add_raw_file_args(raw_sync_parser)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "everef-market-history":
        load_info = run_everef_market_history_pipeline(
            build_everef_market_history_config(args)
        )
        print(load_info)
        return 0

    if args.command == "raw-files" and args.raw_command == "sync-everef-market-history":
        records = sync_everef_market_history_files(build_raw_files_sync_config(args))
        print(f"Synced {len(records)} Everef market history raw files")
        return 0

    parser.print_help()
    return 2


def build_everef_market_history_config(
    args: argparse.Namespace,
) -> EverefMarketHistoryCliConfig:
    """Map parsed args to typed Everef market-history CLI config."""
    config_kwargs = {
        "date_range": DateRangeCliConfig(
            start_date=args.start_date,
            end_date=args.end_date,
        ),
        "storage": _build_storage_config(args),
        "raw_files": _build_raw_files_config(args),
        "ducklake_name": args.ducklake_name,
        "ducklake_catalog": args.ducklake_catalog,
        "ducklake_storage": args.ducklake_storage,
        "base_url": args.base_url,
        "chunksize": args.chunksize,
        "sync_raw": args.sync_raw,
        "dev_mode": args.dev_mode,
    }
    config_kwargs["check_headers"] = args.check_headers
    _set_if_present(config_kwargs, args, "pipeline_name")
    _set_if_present(config_kwargs, args, "dataset_name")
    _set_if_present(config_kwargs, args, "destination")
    _set_if_present(config_kwargs, args, "input_source")
    _set_if_present(config_kwargs, args, "loader_file_format")
    return EverefMarketHistoryCliConfig(**config_kwargs)


def build_raw_files_sync_config(args: argparse.Namespace) -> RawFilesSyncCliConfig:
    """Map parsed args to typed raw-file sync CLI config."""
    config_kwargs = {
        "date_range": DateRangeCliConfig(
            start_date=args.start_date,
            end_date=args.end_date,
        ),
        "storage": _build_storage_config(args),
        "raw_files": _build_raw_files_config(args),
        "base_url": args.base_url,
    }
    config_kwargs["check_headers"] = args.check_headers
    return RawFilesSyncCliConfig(
        **config_kwargs,
    )


def _set_if_present(
    config_kwargs: dict[str, object],
    args: argparse.Namespace,
    arg_name: str,
) -> None:
    if hasattr(args, arg_name):
        config_kwargs[arg_name] = getattr(args, arg_name)


def _build_storage_config(args: argparse.Namespace) -> StorageCliConfig:
    config_kwargs: dict[str, object] = {"data_root": args.data_root}
    _set_if_present(config_kwargs, args, "storage_target")
    return StorageCliConfig(**config_kwargs)


def _build_raw_files_config(args: argparse.Namespace) -> RawFilesCliConfig:
    return RawFilesCliConfig(
        raw_root=args.raw_root,
        raw_ledger_url=args.raw_ledger_url,
        raw_max_copies_per_date=args.raw_max_copies_per_date,
    )


if __name__ == "__main__":
    raise SystemExit(main())
