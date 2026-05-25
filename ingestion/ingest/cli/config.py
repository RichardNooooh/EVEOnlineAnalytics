from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DateRangeCliConfig:
    start_date: str
    end_date: str


@dataclass(frozen=True)
class RawFilesCliConfig:
    raw_root: str | None = None
    raw_ledger_url: str | None = None
    raw_max_copies_per_date: int | None = None


@dataclass(frozen=True)
class DuckLakeCliConfig:
    ducklake_name: str | None = None
    ducklake_catalog: str | None = None
    ducklake_storage: str | None = None


@dataclass(frozen=True)
class EverefMarketHistoryCliConfig:
    date_range: DateRangeCliConfig
    raw_files: RawFilesCliConfig = field(default_factory=RawFilesCliConfig)
    ducklake: DuckLakeCliConfig = field(default_factory=DuckLakeCliConfig)


@dataclass(frozen=True)
class EverefMarketOrdersCliConfig:
    date_range: DateRangeCliConfig
    raw_files: RawFilesCliConfig = field(default_factory=RawFilesCliConfig)
    ducklake: DuckLakeCliConfig = field(default_factory=DuckLakeCliConfig)
