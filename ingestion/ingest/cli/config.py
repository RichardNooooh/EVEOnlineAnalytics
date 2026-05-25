from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DateRangeCliConfig:
    start_date: str
    end_date: str


@dataclass(frozen=True)
class RawFilesCliConfig:
    raw_root: str
    raw_ledger_url: str | None = None
    raw_max_copies_per_date: int | None = None


@dataclass(frozen=True)
class DuckLakeCliConfig:
    ducklake_catalog: str
    ducklake_metadata_schema: str


@dataclass(frozen=True)
class EverefCliConfig:
    start_date: str
    end_date: str
    data_root: str
    raw_files: RawFilesCliConfig
    ducklake: DuckLakeCliConfig
