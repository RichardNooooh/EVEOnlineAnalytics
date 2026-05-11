"""Command-line entrypoint for ingestion jobs."""

from __future__ import annotations

import argparse
import logging

from eve_market_ingestion.pipelines.everef import run_everef_market_history_pipeline
from eve_market_ingestion.pipelines.everef import DATA_ROOT_ENV_VAR
from eve_market_ingestion.pipelines.everef import DUCKLAKE_CATALOG_ENV_VAR
from eve_market_ingestion.pipelines.everef import DUCKLAKE_NAME_ENV_VAR
from eve_market_ingestion.pipelines.everef import DUCKLAKE_STORAGE_ENV_VAR
from eve_market_ingestion.pipelines.everef import LOCAL_STORAGE_TARGET
from eve_market_ingestion.pipelines.everef import STORAGE_TARGETS


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
    everef_parser.add_argument("--loader-file-format", default="parquet")
    everef_parser.add_argument("--dev-mode", action="store_true")

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
            loader_file_format=args.loader_file_format,
            dev_mode=args.dev_mode,
        )
        print(load_info)
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
