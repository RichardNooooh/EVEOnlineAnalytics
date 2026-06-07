from __future__ import annotations

import argparse
from pathlib import Path

from eve_ingest.cli.config import (
    DuckLakeBootstrapCliConfig,
    DuckLakeCliConfig,
    EverefCliConfig,
    EverefReferencesCliConfig,
    RawFilesCliConfig,
)
from eve_ingest.util import parse_iso_date


def build_everef_config(args: argparse.Namespace) -> EverefCliConfig:
    start_date = parse_iso_date(args.start_date, field_name="start_date")
    end_date = parse_iso_date(args.end_date, field_name="end_date")
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    return EverefCliConfig(
        start_date=start_date,
        end_date=end_date,
        data_root=args.data_root,
        raw_files=build_raw_files_config(args),
        ducklake=build_ducklake_config(args),
    )


def build_raw_files_config(args: argparse.Namespace) -> RawFilesCliConfig:
    if not args.raw_ledger_url:
        raise ValueError("raw_ledger_url must not be empty")
    if not str(args.raw_ledger_url).startswith(("postgresql://", "postgres://")):
        raise ValueError("raw_ledger_url must be a PostgreSQL URL")
    return RawFilesCliConfig(
        raw_root=str(Path(args.data_root) / "raw"),
        raw_ledger_url=args.raw_ledger_url,
    )


def build_everef_references_config(args: argparse.Namespace) -> EverefReferencesCliConfig:
    return EverefReferencesCliConfig(
        data_root=args.data_root,
        raw_files=build_raw_files_config(args),
        ducklake=build_ducklake_config(args),
    )


def build_ducklake_config(args: argparse.Namespace) -> DuckLakeCliConfig:
    timeout_seconds = float(args.ducklake_lock_wait_timeout_seconds)
    if timeout_seconds <= 0:
        raise ValueError("ducklake_lock_wait_timeout_seconds must be greater than 0")
    pg_pool_max_connections = int(args.ducklake_pg_pool_max_connections)
    if pg_pool_max_connections < 0:
        raise ValueError("ducklake_pg_pool_max_connections must be non-negative")
    pg_pool_wait_timeout_millis = int(args.ducklake_pg_pool_wait_timeout_millis)
    if pg_pool_wait_timeout_millis <= 0:
        raise ValueError("ducklake_pg_pool_wait_timeout_millis must be greater than 0")
    pg_pool_acquire_mode = str(args.ducklake_pg_pool_acquire_mode)
    if pg_pool_acquire_mode not in {"force", "wait", "try"}:
        raise ValueError("ducklake_pg_pool_acquire_mode must be one of: force, wait, try")
    return DuckLakeCliConfig(
        ducklake_catalog=args.ducklake_catalog,
        ducklake_metadata_schema=args.ducklake_metadata_schema,
        lock_wait_timeout_seconds=timeout_seconds,
        pg_pool_max_connections=pg_pool_max_connections,
        pg_pool_wait_timeout_millis=pg_pool_wait_timeout_millis,
        pg_pool_acquire_mode=pg_pool_acquire_mode,
    )


def build_ducklake_bootstrap_config(args: argparse.Namespace) -> DuckLakeBootstrapCliConfig:
    return DuckLakeBootstrapCliConfig(
        data_root=args.data_root,
        ducklake=build_ducklake_config(args),
    )
