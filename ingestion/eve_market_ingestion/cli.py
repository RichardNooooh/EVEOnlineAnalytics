"""Command-line entrypoint for ingestion jobs."""

from __future__ import annotations

import argparse
import logging

from eve_market_ingestion.pipelines.everef import run_everef_market_history_pipeline
from eve_market_ingestion.pipelines.everef import BUCKET_URL_ENV_VAR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EVE market ingestion jobs.")
    subparsers = parser.add_subparsers(dest="command")

    everef_parser = subparsers.add_parser(
        "everef-market-history",
        help="Ingest Everef daily market history CSV archives.",
    )
    everef_parser.add_argument("--start-date", required=True, help="Inclusive YYYY-MM-DD date.")
    everef_parser.add_argument("--end-date", required=True, help="Inclusive YYYY-MM-DD date.")
    everef_parser.add_argument("--pipeline-name", default="everef_market_history")
    everef_parser.add_argument("--dataset-name", default="everef_market_history")
    everef_parser.add_argument("--destination", default="filesystem")
    everef_parser.add_argument(
        "--bucket-url",
        default=None,
        help=(
            "Filesystem destination URL, for example file:///tmp/eve-market/raw. "
            f"Defaults to {BUCKET_URL_ENV_VAR}."
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
            bucket_url=args.bucket_url,
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
