"""Command-line entrypoint for ingestion jobs."""

from __future__ import annotations

import argparse
import logging

from eve_market_ingestion.everef_market_history_files import BASE_URL
from eve_market_ingestion.pipelines.everef import run_everef_market_history_pipeline
from eve_market_ingestion.pipelines.everef import DATA_ROOT_ENV_VAR
from eve_market_ingestion.pipelines.everef import DUCKLAKE_CATALOG_ENV_VAR
from eve_market_ingestion.pipelines.everef import DUCKLAKE_NAME_ENV_VAR
from eve_market_ingestion.pipelines.everef import DUCKLAKE_STORAGE_ENV_VAR
from eve_market_ingestion.pipelines.everef import LOCAL_STORAGE_TARGET
from eve_market_ingestion.pipelines.everef import STORAGE_TARGETS
from eve_market_ingestion.raw_files.config import RAW_FILES_DB_ENV_VAR
from eve_market_ingestion.raw_files.config import RAW_FILES_ROOT_ENV_VAR
from eve_market_ingestion.raw_files.config import resolve_raw_files_config
from eve_market_ingestion.raw_files.everef import acquire_everef_market_history_files
from eve_market_ingestion.sources.everef_market_history import INPUT_SOURCES
from eve_market_ingestion.sources.everef_market_history import URL_INPUT_SOURCE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EVE market ingestion jobs.")
    subparsers = parser.add_subparsers(dest="command")

    everef_parser = subparsers.add_parser(
        "everef-market-history",
        help="Ingest Everef daily market history CSV archives.",
    )
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
        "--raw-ledger-db",
        default=None,
        help=f"Raw source-file SQLite ledger path. Overrides {RAW_FILES_DB_ENV_VAR}.",
    )
    everef_parser.add_argument("--loader-file-format", default="parquet")
    everef_parser.add_argument("--dev-mode", action="store_true")

    raw_files_parser = subparsers.add_parser(
        "raw-files",
        help="Manage raw source-file acquisition caches.",
    )
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
        "--raw-ledger-db",
        default=None,
        help=f"Raw source-file SQLite ledger path. Overrides {RAW_FILES_DB_ENV_VAR}.",
    )

    return parser


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
            raw_ledger_db=args.raw_ledger_db,
            loader_file_format=args.loader_file_format,
            dev_mode=args.dev_mode,
        )
        print(load_info)
        return 0

    if args.command == "raw-files" and args.raw_command == "sync-everef-market-history":
        config = resolve_raw_files_config(
            raw_root=args.raw_root,
            db_path=args.raw_ledger_db,
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
