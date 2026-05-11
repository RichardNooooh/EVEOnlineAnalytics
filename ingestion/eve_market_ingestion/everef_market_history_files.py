"""Everef market history source-file helpers."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

BASE_URL = "https://data.everef.net/market-history"


def parse_market_history_date(value: str | date) -> date:
    """Parse an ISO date or return an existing date instance."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def market_history_file_url(market_date: date, base_url: str = BASE_URL) -> str:
    """Build the Everef daily market history CSV URL."""
    return (
        f"{base_url.rstrip('/')}/{market_date.year}/"
        f"market-history-{market_date.isoformat()}.csv.bz2"
    )


def market_history_file_name(market_date: date) -> str:
    """Return the canonical Everef daily market history file name."""
    return f"market-history-{market_date.isoformat()}.csv.bz2"


def iter_dates(start_date: date, end_date: date) -> Iterator[date]:
    """Yield inclusive dates between start_date and end_date."""
    if end_date < start_date:
        msg = "end_date must be on or after start_date"
        raise ValueError(msg)

    for offset in range((end_date - start_date).days + 1):
        yield start_date + timedelta(days=offset)
