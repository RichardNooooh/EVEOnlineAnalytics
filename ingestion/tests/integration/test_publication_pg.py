from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from eve_ingest.raw_objects.ledger import RawObjectLedger
from eve_ingest.raw_objects.ledger.models import PublicationContext, RawObjectRef
from eve_ingest.raw_objects.primitives import UpdateMode
from eve_ingest.workflows.raw_file_workflow import (
    PublicationScopeLockError,
    _hold_publication_scope_locks,
    _postgresql_uri,
    _publication_scope_lock_key,
)


@pytest.fixture
def ref() -> RawObjectRef:
    suffix = uuid4().hex
    return RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash=f"hash-pub-{suffix}",
        identity_key={"k": suffix},
        update_mode=UpdateMode.SNAPSHOT,
    )


@pytest.mark.integration
def test_mark_published_inserts_row(pg_url: str, ref: RawObjectRef) -> None:
    ledger = RawObjectLedger(ledger_url=pg_url)
    with ledger.transaction() as tx:
        tx.publications.mark_published(
            ref=ref,
            sha256="abc",
            version_id="v-1",
            context=PublicationContext(
                published_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                publication_scope="test-scope",
                publisher_run_id="run-1",
            ),
        )
        assert tx.publications.is_published(ref=ref, sha256="abc") is True
        assert tx.publications.is_published(ref=ref, sha256="def") is False
    ledger.close()


@pytest.mark.integration
def test_mark_published_is_idempotent(pg_url: str, ref: RawObjectRef) -> None:
    ledger = RawObjectLedger(ledger_url=pg_url)
    ctx = PublicationContext()
    with ledger.transaction() as tx:
        tx.publications.mark_published(ref=ref, sha256="abc", version_id="v-1", context=ctx)
        tx.publications.mark_published(ref=ref, sha256="abc", version_id="v-1", context=ctx)
        assert tx.publications.is_published(ref=ref, sha256="abc") is True
    ledger.close()


@pytest.mark.integration
def test_is_published_returns_false_for_unpublished(pg_url: str, ref: RawObjectRef) -> None:
    ledger = RawObjectLedger(ledger_url=pg_url)
    with ledger.transaction() as tx:
        tx.publications.mark_published(
            ref=ref,
            sha256="abc",
            version_id="v-1",
            context=PublicationContext(),
        )
        assert tx.publications.is_published(ref=ref, sha256="abc") is True
        assert tx.publications.is_published(ref=ref, sha256="xyz") is False
    ledger.close()


@pytest.mark.integration
def test_filter_published_returns_correct_subset(pg_url: str) -> None:
    ref1 = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash="hash-f1",
        identity_key={"k": "1"},
        update_mode=UpdateMode.SNAPSHOT,
    )
    ref2 = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash="hash-f2",
        identity_key={"k": "2"},
        update_mode=UpdateMode.SNAPSHOT,
    )
    ledger = RawObjectLedger(ledger_url=pg_url)
    ctx = PublicationContext()
    with ledger.transaction() as tx:
        tx.publications.mark_published(ref=ref1, sha256="s1", version_id="v-1", context=ctx)
        tx.publications.mark_published(ref=ref2, sha256="s2", version_id="v-2", context=ctx)

        published = tx.publications.filter_published(
            group_key=("test", "test_ds"),
            versions=[("hash-f1", "s1"), ("hash-f2", "s2"), ("hash-f1", "unknown")],
        )
        assert published == {("hash-f1", "s1"), ("hash-f2", "s2")}
    ledger.close()


@pytest.mark.integration
def test_mark_published_many_inserts_multiple_rows(pg_url: str) -> None:
    ref1 = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash="hash-mm1",
        identity_key={"k": "1"},
        update_mode=UpdateMode.SNAPSHOT,
    )
    ref2 = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash="hash-mm2",
        identity_key={"k": "2"},
        update_mode=UpdateMode.SNAPSHOT,
    )
    ctx = PublicationContext()
    ledger = RawObjectLedger(ledger_url=pg_url)
    with ledger.transaction() as tx:
        tx.publications.mark_published_many(
            [
                (ref1, "s1", "v-1", ctx),
                (ref2, "s2", "v-2", ctx),
            ]
        )
        assert tx.publications.is_published(ref=ref1, sha256="s1") is True
        assert tx.publications.is_published(ref=ref2, sha256="s2") is True
    ledger.close()


@pytest.mark.integration
def test_hold_publication_scope_locks_times_out_on_contention(pg_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    publication_scope = "raw:market_history:source_date=2026-01-01"
    connection = psycopg.connect(_postgresql_uri(pg_url), autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("select pg_advisory_lock(%s)", (_publication_scope_lock_key(publication_scope),))

        monkeypatch.setattr(
            "eve_ingest.workflows.raw_file_workflow._PUBLICATION_SCOPE_LOCK_WAIT_TIMEOUT_SECONDS",
            0.1,
        )

        with pytest.raises(PublicationScopeLockError, match=publication_scope):
            with _hold_publication_scope_locks(catalog_url=pg_url, publication_scopes=(publication_scope,)):
                pytest.fail("lock acquisition should have timed out")
    finally:
        connection.close()
