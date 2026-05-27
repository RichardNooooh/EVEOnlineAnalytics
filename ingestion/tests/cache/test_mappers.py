from __future__ import annotations

import pytest

from ingest.cache.ledger.mappers import normalize_ledger_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql+psycopg2://user:pass@host/db",
            "postgresql+psycopg2://user:pass@host/db",
        ),
        (
            "postgresql+psycopg://user:pass@host/db",
            "postgresql+psycopg://user:pass@host/db",
        ),
        (
            "postgresql://user:pass@host/db",
            "postgresql+psycopg://user:pass@host/db",
        ),
        (
            "postgres://user:pass@host/db",
            "postgresql+psycopg://user:pass@host/db",
        ),
    ],
)
def test_normalize_ledger_url_passes_through_or_transforms(url: str, expected: str) -> None:
    assert normalize_ledger_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///tmp/db.sqlite",
        "mysql://user:pass@host/db",
        "https://example.com/db",
    ],
)
def test_normalize_ledger_url_rejects_non_postgres(url: str) -> None:
    with pytest.raises(ValueError, match="ledger_url must be a PostgreSQL URL"):
        normalize_ledger_url(url)
