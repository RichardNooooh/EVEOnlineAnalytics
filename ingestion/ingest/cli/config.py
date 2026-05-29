from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DateRangeCliConfig:
    start_date: str
    end_date: str


@dataclass(frozen=True)
class RawFilesCliConfig:
    raw_root: str
    raw_ledger_url: str


@dataclass(frozen=True)
class DuckLakeCliConfig:
    ducklake_catalog: str
    ducklake_metadata_schema: str


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
