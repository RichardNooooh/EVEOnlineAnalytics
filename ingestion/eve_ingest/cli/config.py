from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DateRangeCliConfig:
    start_date: str
    end_date: str


class RawFilesCliConfig:
    def __init__(self, *, raw_root: str, raw_ledger_url: str, raw_download_workers: int) -> None:
        if raw_download_workers < 1:
            raise ValueError("raw_download_workers must be at least 1")
        self.raw_root = raw_root
        self.raw_ledger_url = raw_ledger_url
        self.raw_download_workers = raw_download_workers


@dataclass(frozen=True)
class DuckLakeCliConfig:
    ducklake_catalog: str
    ducklake_metadata_schema: str
    lock_wait_timeout_seconds: float
    pg_pool_max_connections: int
    pg_pool_wait_timeout_millis: int
    pg_pool_acquire_mode: str


@dataclass(frozen=True)
class EverefCliConfig:
    start_date: date
    end_date: date
    data_root: str
    raw_files: RawFilesCliConfig
    ducklake: DuckLakeCliConfig


@dataclass(frozen=True)
class EverefReferencesCliConfig:
    data_root: str
    raw_files: RawFilesCliConfig
    ducklake: DuckLakeCliConfig


@dataclass(frozen=True)
class DuckLakeBootstrapCliConfig:
    data_root: str
    ducklake: DuckLakeCliConfig
