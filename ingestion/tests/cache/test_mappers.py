from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ingest.cache.ledger.mappers import (
    entity_to_row,
    normalize_ledger_url,
    raw_object_publication_values,
    raw_object_seen_values,
    raw_object_values,
    raw_object_version_values,
)
from ingest.cache.models import (
    PublicationContext,
    RawObjectEntry,
    RawObjectRef,
    RawObjectVersion,
    RevalidationMetadata,
    UpdateMode,
)


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


def _entry() -> RawObjectEntry:
    return RawObjectEntry(
        id="obj-1",
        ref=RawObjectRef(
            source_name="everef",
            dataset_name="market-history",
            identity_hash="abc123",
            identity_key={"date": "2026-01-01"},
            update_mode=UpdateMode.SNAPSHOT,
        ),
        identity_key={"date": "2026-01-01"},
        update_mode=UpdateMode.SNAPSHOT,
        created_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        last_checked_at=datetime(2026, 1, 1, 12, 30, tzinfo=UTC),
        revalidation=RevalidationMetadata(
            etag='"e1"',
            last_modified="Mon, 01 Jan 2026 12:00:00 GMT",
            content_length=100,
        ),
    )


def _version() -> RawObjectVersion:
    return RawObjectVersion(
        id="v-1",
        raw_object_id="obj-1",
        source_url="https://example.com/file.csv",
        fetched_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        revalidation=RevalidationMetadata(etag='"e1"', content_length=100),
        sha256="sha-abc",
        local_path="/tmp/file.csv",
        storage_encoding="csv",
    )


class TestEntityToRow:
    def test_raw_object_full(self) -> None:
        entry = _entry()
        result = raw_object_values(entry)
        assert result == {
            "id": "obj-1",
            "source_name": "everef",
            "dataset_name": "market-history",
            "identity_key": {"date": "2026-01-01"},
            "identity_hash": "abc123",
            "update_mode": UpdateMode.SNAPSHOT,
            "created_at": entry.created_at,
            "last_checked_at": entry.last_checked_at,
            "etag": '"e1"',
            "last_modified": "Mon, 01 Jan 2026 12:00:00 GMT",
            "content_length": 100,
        }

    def test_raw_object_seen_subset(self) -> None:
        result = raw_object_seen_values(_entry())
        assert result == {
            "last_checked_at": _entry().last_checked_at,
            "etag": '"e1"',
            "last_modified": "Mon, 01 Jan 2026 12:00:00 GMT",
            "content_length": 100,
        }

    def test_raw_object_version(self) -> None:
        v = _version()
        result = raw_object_version_values(v)
        assert result == {
            "id": "v-1",
            "raw_object_id": "obj-1",
            "source_url": "https://example.com/file.csv",
            "fetched_at": v.fetched_at,
            "etag": '"e1"',
            "last_modified": None,
            "content_length": 100,
            "sha256": "sha-abc",
            "local_path": "/tmp/file.csv",
            "storage_encoding": "csv",
        }

    def test_raw_object_publication(self) -> None:
        ref = RawObjectRef(
            source_name="everef",
            dataset_name="market-history",
            identity_hash="abc123",
            identity_key={"date": "2026-01-01"},
            update_mode=UpdateMode.SNAPSHOT,
        )
        ctx = PublicationContext(
            published_at=datetime(2026, 1, 1, 13, 0, tzinfo=UTC),
            publication_scope="scope-1",
            publisher_run_id="run-1",
        )
        result = raw_object_publication_values(
            ref=ref,
            sha256="sha-abc",
            version_id="v-1",
            context=ctx,
        )
        assert result["source_name"] == "everef"
        assert result["dataset_name"] == "market-history"
        assert result["identity_hash"] == "abc123"
        assert result["sha256"] == "sha-abc"
        assert result["version_id"] == "v-1"
        assert result["published_at"] == ctx.published_at
        assert result["publication_scope"] == "scope-1"
        assert result["publisher_run_id"] == "run-1"
        assert isinstance(result["id"], str)
        assert len(result["id"]) == 32

    def test_entity_to_row_basic(self) -> None:
        entry = _entry()
        from ingest.cache.ledger.column_maps import RAW_OBJECT_COLUMNS

        result = entity_to_row(entry, RAW_OBJECT_COLUMNS)
        assert result["source_name"] == "everef"
        assert result["identity_key"] == {"date": "2026-01-01"}

    def test_entity_to_row_with_overrides(self) -> None:
        entry = _entry()
        from ingest.cache.ledger.column_maps import RAW_OBJECT_COLUMNS

        result = entity_to_row(entry, RAW_OBJECT_COLUMNS, overrides={"source_name": "override"})
        assert result["source_name"] == "override"
        assert result["id"] == "obj-1"

    def test_entity_to_row_handles_none_field_path(self) -> None:
        from ingest.cache.ledger.column_maps import RAW_OBJECT_PUBLICATION_COLUMNS
        from ingest.cache.models import PublicationContext

        ctx = PublicationContext()
        result = entity_to_row(ctx, RAW_OBJECT_PUBLICATION_COLUMNS)
        assert "id" not in result
        assert "published_at" in result
