"""Command-line entrypoint for ingestion jobs."""

from __future__ import annotations

import argparse
import logging

from ingest.clients.everef import BASE_URL
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
    resolve_raw_files_config,
)
from ingest.raw_files.everef import acquire_everef_market_history_files
from ingest.sources.everef import (
    INPUT_SOURCES,
    URL_INPUT_SOURCE,
)
from ingest.storage_config import (
    DATA_ROOT_ENV_VAR,
    LOCAL_STORAGE_TARGET,
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


def build_everef_parser(everef_parser: argparse.ArgumentParser) -> None:
    everef_parser.add_argument(
        "--start-date", required=True, help="Inclusive YYYY-MM-DD date."
    )
    everef_parser.add_argument(
        "--end-date", required=True, help="Inclusive YYYY-MM-DD date."
    )
    everef_parser.add_argument("--pipeline-name", default="everef_market_history")
    everef_parser.add_argument("--dataset-name", default="everef_market_history")
    everef_parser.add_argument("--destination", default="ducklake")
    everef_parser.add_argument(
        "--ducklake-name",
        default=None,
        help=(
            "DuckLake attach name. "
            f"Overrides {DUCKLAKE_NAME_ENV_VAR}, then defaults to eve_market."
        ),
    )
    everef_parser.add_argument(
        "--ducklake-catalog",
        default=None,
        help=(
            "DuckLake catalog URL. "
            f"Overrides {DUCKLAKE_CATALOG_ENV_VAR}, then defaults to local sqlite."
        ),
    )
    everef_parser.add_argument(
        "--ducklake-storage",
        default=None,
        help=(
            "DuckLake storage URL. "
            f"Overrides {DUCKLAKE_STORAGE_ENV_VAR}, then --storage-target defaults."
        ),
    )
    everef_parser.add_argument(
        "--storage-target",
        choices=STORAGE_TARGETS,
        default=LOCAL_STORAGE_TARGET,
        help=(
            "Default DuckLake storage target when --ducklake-storage "
            "and env override are unset."
        ),
    )
    everef_parser.add_argument(
        "--data-root",
        default=None,
        help=(
            "Mounted storage root used with --storage-target mounted; "
            f"env fallback {DATA_ROOT_ENV_VAR}."
        ),
    )
    everef_parser.add_argument("--base-url", default=None)
    everef_parser.add_argument("--chunksize", type=int, default=None)
    everef_parser.add_argument(
        "--input-source",
        choices=INPUT_SOURCES,
        default=URL_INPUT_SOURCE,
        help="Read CSVs from source URLs or from the raw-file cache.",
    )
    everef_parser.add_argument(
        "--sync-raw",
        action="store_true",
        help="Download raw files first, then load from the raw-file cache.",
    )
    everef_parser.add_argument(
        "--raw-root",
        default=None,
        help=f"Raw source-file cache root. Overrides {RAW_FILES_ROOT_ENV_VAR}.",
    )
    everef_parser.add_argument(
        "--raw-ledger-url",
        default=None,
        help=f"Raw source-file ledger URL. Overrides {RAW_FILES_LEDGER_URL_ENV_VAR}.",
    )
    everef_parser.add_argument(
        "--raw-max-copies-per-date",
        default=None,
        help=(
            "Maximum raw file copies to keep per source date; 0 disables deletion. "
            f"Overrides {RAW_FILES_MAX_COPIES_PER_DATE_ENV_VAR}."
        ),
    )
    everef_parser.add_argument("--loader-file-format", default="parquet")
    everef_parser.add_argument("--dev-mode", action="store_true")


def build_raw_files_parser(raw_files_parser: argparse.ArgumentParser) -> None:
    raw_subparsers = raw_files_parser.add_subparsers(dest="raw_command")
    raw_subparsers.required = True
    raw_sync_parser = raw_subparsers.add_parser(
        "sync-everef-market-history",
        help="Download Everef market history CSV archives into the raw cache.",
    )
    raw_sync_parser.add_argument(
        "--start-date", required=True, help="Inclusive YYYY-MM-DD date."
    )
    raw_sync_parser.add_argument(
        "--end-date", required=True, help="Inclusive YYYY-MM-DD date."
    )
    raw_sync_parser.add_argument(
        "--storage-target",
        choices=STORAGE_TARGETS,
        default=LOCAL_STORAGE_TARGET,
        help="Default raw cache target when --raw-root and env override are unset.",
    )
    raw_sync_parser.add_argument(
        "--data-root",
        default=None,
        help=(
            "Mounted storage root used with --storage-target mounted; "
            f"env fallback {DATA_ROOT_ENV_VAR}."
        ),
    )
    raw_sync_parser.add_argument("--base-url", default=None)
    raw_sync_parser.add_argument(
        "--raw-root",
        default=None,
        help=f"Raw source-file cache root. Overrides {RAW_FILES_ROOT_ENV_VAR}.",
    )
    raw_sync_parser.add_argument(
        "--raw-ledger-url",
        default=None,
        help=f"Raw source-file ledger URL. Overrides {RAW_FILES_LEDGER_URL_ENV_VAR}.",
    )
    raw_sync_parser.add_argument(
        "--raw-max-copies-per-date",
        default=None,
        help=(
            "Maximum raw file copies to keep per source date; 0 disables deletion. "
            f"Overrides {RAW_FILES_MAX_COPIES_PER_DATE_ENV_VAR}."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "everef-market-history":
        load_info = run_everef_market_history_pipeline(
            args.start_date,
            args.end_date,
            pipeline_name=args.pipeline_name,
            dataset_name=args.dataset_name,
            destination=args.destination,
            ducklake_name=args.ducklake_name,
            ducklake_catalog=args.ducklake_catalog,
            ducklake_storage=args.ducklake_storage,
            storage_target=args.storage_target,
            data_root=args.data_root,
            base_url=args.base_url,
            chunksize=args.chunksize,
            input_source=args.input_source,
            sync_raw=args.sync_raw,
            raw_root=args.raw_root,
            raw_ledger_url=args.raw_ledger_url,
            raw_max_copies_per_date=args.raw_max_copies_per_date,
            loader_file_format=args.loader_file_format,
            dev_mode=args.dev_mode,
        )
        print(load_info)
        return 0

    if args.command == "raw-files" and args.raw_command == "sync-everef-market-history":
        config = resolve_raw_files_config(
            raw_root=args.raw_root,
            ledger_url=args.raw_ledger_url,
            max_copies_per_date=args.raw_max_copies_per_date,
            storage_target=args.storage_target,
            data_root=args.data_root,
        )
        records = acquire_everef_market_history_files(
            args.start_date,
            args.end_date,
            base_url=args.base_url or BASE_URL,
            config=config,
        )
        print(f"Synced {len(records)} Everef market history raw files")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
