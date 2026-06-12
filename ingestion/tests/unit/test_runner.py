from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from eve_ingest.ducklake.provenance_metadata import build_source_object_metadata
from eve_ingest.ducklake.raw_tables import compute_source_ref_id
from eve_ingest.ducklake.sql import quote_sql_string
from eve_ingest.raw_objects import AcquiredRawObject, AcquisitionStatus
from eve_ingest.raw_objects.http_models import RevalidationMetadata
from eve_ingest.raw_objects.ledger.models import RawObjectEntry, RawObjectRef, RawObjectVersion
from eve_ingest.raw_objects.primitives import UpdateMode


def test_quote_sql_string() -> None:
    quoted = quote_sql_string("test'value")
    assert quoted == "'test''value'"


def test_source_ref_id() -> None:
    expected = hashlib.sha256(b"everef|test|https://example.com/test").hexdigest()
    ref_id = compute_source_ref_id(
        source_system="everef",
        endpoint="test",
        source_url="https://example.com/test",
    )
    assert ref_id == expected


def test_build_source_object_metadata() -> None:
    source_url = "https://example.com/meta.csv"
    ref_id = compute_source_ref_id(
        source_system="everef",
        endpoint="meta_test",
        source_url=source_url,
    )

    ref = RawObjectRef(
        source_name="everef",
        dataset_name="meta_test",
        identity_hash="abc",
        identity_key={"source_date": "2026-01-01"},
        update_mode=UpdateMode.SNAPSHOT,
    )
    raw_object = RawObjectEntry(
        id="obj-1",
        ref=ref,
        created_at=datetime(2026, 1, 2, 11, 1, 55, tzinfo=UTC),
    )
    version = RawObjectVersion(
        id="ver-1",
        raw_object_id="obj-1",
        source_url=source_url,
        fetched_at=datetime(2026, 1, 2, 11, 1, 55, tzinfo=UTC),
        revalidation=RevalidationMetadata(content_length=200, last_modified="2026-01-02T12:00:00Z"),
        sha256="abc123",
        local_path="/tmp/test_meta.csv",
        storage_encoding="bz2",
        version_number=1,
    )
    acquired = AcquiredRawObject(
        status=AcquisitionStatus.STORED,
        raw_object=raw_object,
        version=version,
    )

    metadata = build_source_object_metadata(
        acquired,
        "everef",
        "meta_test",
        source_ref_id=ref_id,
        source_market_date=date(2026, 1, 1),
        snapshot_ts=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
    )

    assert metadata["source_ref_id"] == ref_id
    assert metadata["source_system"] == "everef"
    assert metadata["endpoint"] == "meta_test"
    assert metadata["source_url"] == source_url
    assert metadata["status"] == "downloaded"
    assert metadata["content_length"] == 200
    assert metadata["sha256"] == "abc123"
