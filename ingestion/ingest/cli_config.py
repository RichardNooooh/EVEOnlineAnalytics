"""Shared CLI config objects for ingestion commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ingest.input_sources import RAW_CACHE_INPUT_SOURCE
from ingest.storage_config import LOCAL_STORAGE_TARGET


@dataclass(frozen=True)
class DateRangeCliConfig:
    """Shared inclusive date-range CLI config."""

    start_date: str | date
    end_date: str | date


@dataclass(frozen=True)
class StorageCliConfig:
    """Shared storage selection CLI config."""

    storage_target: str = LOCAL_STORAGE_TARGET
    data_root: str | None = None


@dataclass(frozen=True)
class RawFilesCliConfig:
    """Shared raw-file cache CLI config."""

    raw_root: str | None = None
    raw_ledger_url: str | None = None
    raw_max_copies_per_date: int | str | None = None


@dataclass(frozen=True)
class EverefMarketHistoryCliConfig:
    """Typed CLI config for Everef market-history ingestion."""

    date_range: DateRangeCliConfig
    storage: StorageCliConfig = field(default_factory=StorageCliConfig)
    raw_files: RawFilesCliConfig = field(default_factory=RawFilesCliConfig)
    pipeline_name: str = "everef_market_history"
    dataset_name: str = "everef_market_history"
    destination: str = "ducklake"
    ducklake_name: str | None = None
    ducklake_catalog: str | None = None
    ducklake_storage: str | None = None
    base_url: str | None = None
    chunksize: int | None = None
    input_source: str = RAW_CACHE_INPUT_SOURCE
    sync_raw: bool = False
    check_headers: bool = False
    loader_file_format: str = "parquet"
    dev_mode: bool = False


@dataclass(frozen=True)
class RawFilesSyncCliConfig:
    """Typed CLI config for raw Everef market-history sync."""

    date_range: DateRangeCliConfig
    storage: StorageCliConfig = field(default_factory=StorageCliConfig)
    raw_files: RawFilesCliConfig = field(default_factory=RawFilesCliConfig)
    base_url: str | None = None
    check_headers: bool = False
