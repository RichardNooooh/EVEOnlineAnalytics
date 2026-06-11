from __future__ import annotations

import importlib
from datetime import date

import eve_ingest.util as util
import pytest
from eve_ingest.util import (
    iter_dates,
    parse_iso_date,
)


class TestConstants:
    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVE_DUCKLAKE_CATALOG", raising=False)
        monkeypatch.delenv("EVE_RAW_LEDGER_URL", raising=False)
        monkeypatch.delenv("EVE_DUCKLAKE_LOCK_WAIT_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("EVE_DUCKLAKE_PG_POOL_MAX_CONNECTIONS", raising=False)
        monkeypatch.delenv("EVE_DUCKLAKE_PG_POOL_WAIT_TIMEOUT_MILLIS", raising=False)
        monkeypatch.delenv("EVE_DUCKLAKE_PG_POOL_ACQUIRE_MODE", raising=False)
        importlib.reload(util)

    def test_default_data_root(self) -> None:
        assert util.DEFAULT_DATA_ROOT == "/opt/eve-market/data"

    def test_default_raw_root(self) -> None:
        assert util.DEFAULT_RAW_ROOT == "/opt/eve-market/data/raw"

    def test_default_ducklake_raw_data_path(self) -> None:
        assert util.DEFAULT_DUCKLAKE_RAW_DATA_PATH == "/opt/eve-market/data/datasets/ducklake/raw"

    def test_default_ducklake_catalog(self) -> None:
        assert util.DEFAULT_DUCKLAKE_CATALOG == "postgresql://airflow:airflow-local-only@postgres:5432/airflow"

    def test_default_raw_ledger_url(self) -> None:
        assert util.DEFAULT_RAW_LEDGER_URL == "postgresql://raw_files:password@postgres:5432/raw_files"

    def test_default_ducklake_metadata_schema(self) -> None:
        assert util.DEFAULT_DUCKLAKE_METADATA_SCHEMA == "eve_market"

    def test_default_ducklake_postgres_pool_settings(self) -> None:
        assert util.DEFAULT_DUCKLAKE_PG_POOL_MAX_CONNECTIONS == 32
        assert util.DEFAULT_DUCKLAKE_PG_POOL_WAIT_TIMEOUT_MILLIS == 120000
        assert util.DEFAULT_DUCKLAKE_PG_POOL_ACQUIRE_MODE == "wait"


class TestParseIsoDate:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2025-01-01", date(2025, 1, 1)),
            ("2025-12-31", date(2025, 12, 31)),
            ("2024-02-29", date(2024, 2, 29)),
        ],
    )
    def test_valid_date(self, value: str, expected: date) -> None:
        assert parse_iso_date(value, field_name="test_date") == expected

    @pytest.mark.parametrize(
        ("value", "field_name"),
        [
            ("not-a-date", "start_date"),
            ("2025/01/01", "end_date"),
            ("2025-13-01", "date_arg"),
            ("2025-00-01", "month_arg"),
            ("", "empty_arg"),
        ],
    )
    def test_invalid_date_raises(self, value: str, field_name: str) -> None:
        with pytest.raises(ValueError, match=f"{field_name} must be a valid YYYY-MM-DD date"):
            parse_iso_date(value, field_name=field_name)


class TestIterDates:
    def test_single_day(self) -> None:
        d = date(2025, 6, 1)
        assert list(iter_dates(d, d)) == [d]

    def test_two_days(self) -> None:
        result = list(iter_dates(date(2025, 6, 1), date(2025, 6, 2)))
        assert result == [date(2025, 6, 1), date(2025, 6, 2)]

    @pytest.mark.parametrize(
        ("start", "end", "expected"),
        [
            (date(2025, 1, 1), date(2025, 1, 5), [date(2025, 1, d) for d in range(1, 6)]),
            (date(2025, 1, 31), date(2025, 2, 2), [date(2025, 1, 31), date(2025, 2, 1), date(2025, 2, 2)]),
            (
                date(2024, 12, 30),
                date(2025, 1, 2),
                [date(2024, 12, 30), date(2024, 12, 31), date(2025, 1, 1), date(2025, 1, 2)],
            ),
        ],
    )
    def test_date_ranges(self, start: date, end: date, expected: list[date]) -> None:
        assert list(iter_dates(start, end)) == expected

    def test_leap_year(self) -> None:
        result = list(iter_dates(date(2024, 2, 28), date(2024, 3, 1)))
        assert result == [date(2024, 2, 28), date(2024, 2, 29), date(2024, 3, 1)]

    def test_start_after_end_yields_empty(self) -> None:
        result = list(iter_dates(date(2025, 6, 5), date(2025, 6, 1)))
        assert result == []
