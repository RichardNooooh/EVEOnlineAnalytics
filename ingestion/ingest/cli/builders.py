from __future__ import annotations

import argparse
from datetime import date

from ingest.cli.config import (
    DateRangeCliConfig,
    DuckLakeCliConfig,
    EverefMarketHistoryCliConfig,
    EverefMarketOrdersCliConfig,
    RawFilesCliConfig,
)


def build_everef_market_history_config(
    args: argparse.Namespace,
) -> EverefMarketHistoryCliConfig:
    return EverefMarketHistoryCliConfig(
        date_range=build_date_range_config(args),
        raw_files=build_raw_files_config(args),
        ducklake=build_ducklake_config(args),
    )


def build_everef_market_orders_config(
    args: argparse.Namespace,
) -> EverefMarketOrdersCliConfig:
    return EverefMarketOrdersCliConfig(
        date_range=build_date_range_config(args),
        raw_files=build_raw_files_config(args),
        ducklake=build_ducklake_config(args),
    )


def build_date_range_config(args: argparse.Namespace) -> DateRangeCliConfig:
    start_date = _parse_iso_date(args.start_date, field_name="start_date")
    end_date = _parse_iso_date(args.end_date, field_name="end_date")
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    return DateRangeCliConfig(start_date=args.start_date, end_date=args.end_date)


def build_raw_files_config(args: argparse.Namespace) -> RawFilesCliConfig:
    if args.raw_max_copies_per_date is not None and args.raw_max_copies_per_date < 0:
        raise ValueError("raw_max_copies_per_date must be greater than or equal to 0")
    return RawFilesCliConfig(
        raw_root=args.raw_root,
        raw_ledger_url=args.raw_ledger_url,
        raw_max_copies_per_date=args.raw_max_copies_per_date,
    )


def build_ducklake_config(args: argparse.Namespace) -> DuckLakeCliConfig:
    return DuckLakeCliConfig(
        ducklake_name=args.ducklake_name,
        ducklake_catalog=args.ducklake_catalog,
        ducklake_storage=args.ducklake_storage,
    )


def _parse_iso_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid YYYY-MM-DD date") from exc
