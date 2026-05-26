from __future__ import annotations

import argparse
from pathlib import Path

from ingest.cli.config import (
    DuckLakeCliConfig,
    EverefCliConfig,
    RawFilesCliConfig,
)
from ingest.util import parse_iso_date


def build_everef_config(args: argparse.Namespace) -> EverefCliConfig:
    start_date = parse_iso_date(args.start_date, field_name="start_date")
    end_date = parse_iso_date(args.end_date, field_name="end_date")
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    return EverefCliConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        data_root=args.data_root,
        raw_files=build_raw_files_config(args),
        ducklake=build_ducklake_config(args),
    )


def build_everef_market_history_config(args: argparse.Namespace) -> EverefCliConfig:
    return build_everef_config(args)


def build_everef_market_orders_config(args: argparse.Namespace) -> EverefCliConfig:
    return build_everef_config(args)


def build_raw_files_config(args: argparse.Namespace) -> RawFilesCliConfig:
    raw_max_copies_per_date = args.raw_max_copies_per_date
    if raw_max_copies_per_date is not None and raw_max_copies_per_date < 0:
        raise ValueError("raw_max_copies_per_date must be greater than or equal to 0")
    if raw_max_copies_per_date == 0:
        raw_max_copies_per_date = None
    if not args.raw_ledger_url:
        raise ValueError("raw_ledger_url must not be empty")
    if not str(args.raw_ledger_url).startswith(("postgresql://", "postgres://")):
        raise ValueError("raw_ledger_url must be a PostgreSQL URL")
    return RawFilesCliConfig(
        raw_root=str(Path(args.data_root) / "raw"),
        raw_ledger_url=args.raw_ledger_url,
        raw_max_copies_per_date=raw_max_copies_per_date,
    )


def build_ducklake_config(args: argparse.Namespace) -> DuckLakeCliConfig:
    return DuckLakeCliConfig(
        ducklake_catalog=args.ducklake_catalog,
        ducklake_metadata_schema=args.ducklake_metadata_schema,
    )
