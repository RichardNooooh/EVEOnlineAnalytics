from __future__ import annotations

from datetime import UTC, datetime
from threading import Barrier, Thread
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from eve_ingest.raw_objects.http_models import RevalidationMetadata
from eve_ingest.raw_objects.ledger import RawObjectLedger
from eve_ingest.raw_objects.ledger.models import RawObjectRef
from eve_ingest.raw_objects.ledger.schema import raw_object_versions, raw_objects
from eve_ingest.raw_objects.primitives import UpdateMode


@pytest.mark.integration
def test_schema_bootstraps_on_first_transaction(pg_url: str) -> None:
    ledger = RawObjectLedger(ledger_url=pg_url)
    with ledger.transaction() as tx:
        result = tx.reader.load_raw_object(
            ref=RawObjectRef(
                source_name="test",
                dataset_name="test_ds",
                identity_hash="nonexistent",
                identity_key={"k": "v"},
                update_mode=UpdateMode.SNAPSHOT,
            )
        )
    assert result is None
    ledger.close()


@pytest.mark.integration
def test_touch_raw_object_creates_and_updates_entry(pg_url: str) -> None:
    ref = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash="hash-touch-create-update",
        identity_key={"k": "v"},
        update_mode=UpdateMode.MUTABLE,
    )
    ledger = RawObjectLedger(ledger_url=pg_url)
    with ledger.transaction() as tx:
        entry1 = tx.writer.touch_raw_object(ref=ref, checked_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
        entry2 = tx.writer.touch_raw_object(
            ref=ref,
            checked_at=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
            revalidation=RevalidationMetadata(etag='"v2"'),
        )
        assert entry2.ref == ref
        assert entry2.last_checked_at == datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
        assert entry2.revalidation.etag == '"v2"'
        assert entry2.id == entry1.id  # same logical object
    ledger.close()


@pytest.mark.integration
def test_rotate_version_inserts_version_and_returns_stale(pg_url: str) -> None:
    ref = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash="hash-3",
        identity_key={"k": "v"},
        update_mode=UpdateMode.MUTABLE,
    )
    ledger = RawObjectLedger(ledger_url=pg_url)
    with ledger.transaction() as tx:
        tx.writer.touch_raw_object(ref=ref, checked_at=datetime.now(UTC))
        result1 = tx.writer.rotate_version(
            ref=ref,
            source_url="https://example.com/v1",
            fetched_at=datetime.now(UTC),
            revalidation=RevalidationMetadata(etag='"v1"'),
            sha256="a" * 64,
            local_path="/tmp/v1",
            storage_encoding="csv",
        )
        assert result1.version.sha256 == "a" * 64
        assert len(result1.stale_versions) == 0

        result2 = tx.writer.rotate_version(
            ref=ref,
            source_url="https://example.com/v2",
            fetched_at=datetime.now(UTC),
            revalidation=RevalidationMetadata(etag='"v2"'),
            sha256="b" * 64,
            local_path="/tmp/v2",
            storage_encoding="csv",
        )
        assert result2.version.sha256 == "b" * 64
        assert len(result2.stale_versions) == 1
        assert result2.stale_versions[0].sha256 == "a" * 64
    ledger.close()


@pytest.mark.integration
def test_rotate_version_keeps_stale_and_increments_version_number(pg_url: str) -> None:
    ref = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash="hash-4",
        identity_key={"k": "v"},
        update_mode=UpdateMode.MUTABLE,
    )
    ledger = RawObjectLedger(ledger_url=pg_url)
    with ledger.transaction() as tx:
        tx.writer.touch_raw_object(ref=ref, checked_at=datetime.now(UTC))
        # First rotation: no stale versions
        r1 = tx.writer.rotate_version(
            ref=ref,
            source_url="https://example.com/v1",
            fetched_at=datetime.now(UTC),
            revalidation=RevalidationMetadata(),
            sha256="a" * 64,
            local_path="/tmp/v1",
            storage_encoding="csv",
        )
        assert len(r1.stale_versions) == 0
        assert r1.version.version_number == 1

        # Second rotation: v1 becomes stale but stays in DB
        r2 = tx.writer.rotate_version(
            ref=ref,
            source_url="https://example.com/v2",
            fetched_at=datetime.now(UTC),
            revalidation=RevalidationMetadata(),
            sha256="b" * 64,
            local_path="/tmp/v2",
            storage_encoding="csv",
        )
        assert len(r2.stale_versions) == 1
        assert r2.stale_versions[0].sha256 == "a" * 64
        assert r2.version.version_number == 2

        # Latest version is still correctly resolved
        raw_object = tx.reader.load_raw_object(ref=ref)
        assert raw_object is not None
        latest = tx.reader.load_latest_version(raw_object.id)
        assert latest is not None
        assert latest.sha256 == "b" * 64
        assert latest.version_number == 2
    ledger.close()


@pytest.mark.integration
def test_transaction_rollback_on_exception(pg_url: str) -> None:
    ref = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash="hash-rollback",
        identity_key={"k": "v"},
        update_mode=UpdateMode.SNAPSHOT,
    )
    ledger = RawObjectLedger(ledger_url=pg_url)
    try:
        with ledger.transaction() as tx:
            tx.writer.touch_raw_object(ref=ref, checked_at=datetime.now(UTC))
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    # After rollback, the entry should not exist
    with ledger.transaction() as tx:
        result = tx.reader.load_raw_object(ref=ref)
    assert result is None
    ledger.close()


@pytest.mark.integration
def test_load_latest_version_returns_most_recent(pg_url: str) -> None:
    ref = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash="hash-latest",
        identity_key={"k": "v"},
        update_mode=UpdateMode.MUTABLE,
    )
    ledger = RawObjectLedger(ledger_url=pg_url)
    with ledger.transaction() as tx:
        tx.writer.touch_raw_object(ref=ref, checked_at=datetime.now(UTC))
        tx.writer.rotate_version(
            ref=ref,
            source_url="https://example.com/v1",
            fetched_at=datetime.now(UTC),
            revalidation=RevalidationMetadata(),
            sha256="a" * 64,
            local_path="/tmp/v1",
            storage_encoding="csv",
        )
        tx.writer.rotate_version(
            ref=ref,
            source_url="https://example.com/v2",
            fetched_at=datetime.now(UTC),
            revalidation=RevalidationMetadata(),
            sha256="b" * 64,
            local_path="/tmp/v2",
            storage_encoding="csv",
        )

        raw_object = tx.reader.load_raw_object(ref=ref)
        assert raw_object is not None
        latest = tx.reader.load_latest_version(raw_object.id)
        assert latest is not None
        assert latest.sha256 == "b" * 64
    ledger.close()


@pytest.mark.integration
def test_load_latest_versions_returns_correct_for_multiple(pg_url: str) -> None:
    ref1 = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash="hash-multi-1",
        identity_key={"k": "1"},
        update_mode=UpdateMode.MUTABLE,
    )
    ref2 = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash="hash-multi-2",
        identity_key={"k": "2"},
        update_mode=UpdateMode.MUTABLE,
    )
    ledger = RawObjectLedger(ledger_url=pg_url)
    with ledger.transaction() as tx:
        tx.writer.touch_raw_object(ref=ref1, checked_at=datetime.now(UTC))
        tx.writer.touch_raw_object(ref=ref2, checked_at=datetime.now(UTC))
        tx.writer.rotate_version(
            ref=ref1,
            source_url="https://example.com/o1-v1",
            fetched_at=datetime.now(UTC),
            revalidation=RevalidationMetadata(),
            sha256="c" * 64,
            local_path="/tmp/o1-v1",
            storage_encoding="csv",
        )
        tx.writer.rotate_version(
            ref=ref2,
            source_url="https://example.com/o2-v1",
            fetched_at=datetime.now(UTC),
            revalidation=RevalidationMetadata(),
            sha256="d" * 64,
            local_path="/tmp/o2-v1",
            storage_encoding="csv",
        )

        raw1 = tx.reader.load_raw_object(ref=ref1)
        raw2 = tx.reader.load_raw_object(ref=ref2)
        assert raw1 is not None and raw2 is not None

        versions = tx.reader.load_latest_versions([raw1.id, raw2.id])
        assert versions[raw1.id].sha256 == "c" * 64
        assert versions[raw2.id].sha256 == "d" * 64
    ledger.close()


@pytest.mark.integration
def test_concurrent_first_touch_creates_one_raw_object(pg_url: str) -> None:
    worker_count = 4
    identity_hash = f"hash-touch-{uuid4().hex}"
    ref = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash=identity_hash,
        identity_key={"k": "concurrent-touch"},
        update_mode=UpdateMode.MUTABLE,
    )
    start = Barrier(worker_count)
    errors: list[BaseException] = []
    raw_object_ids: list[str] = []

    def worker(index: int) -> None:
        ledger = RawObjectLedger(ledger_url=pg_url)
        try:
            start.wait(timeout=5)
            with ledger.transaction() as tx:
                entry = tx.writer.touch_raw_object(
                    ref=ref,
                    checked_at=datetime.now(UTC),
                    revalidation=RevalidationMetadata(etag=f'"v{index}"'),
                )
                raw_object_ids.append(entry.id)
        except BaseException as exc:  # pragma: no cover - surfaced through assertion below
            errors.append(exc)
        finally:
            ledger.close()

    threads = [Thread(target=worker, args=(index,)) for index in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert all(thread.is_alive() is False for thread in threads)
    assert len(raw_object_ids) == worker_count
    assert len(set(raw_object_ids)) == 1

    ledger = RawObjectLedger(ledger_url=pg_url)
    with ledger._engine.begin() as con:
        count = con.execute(
            select(func.count()).select_from(raw_objects).where(raw_objects.c.identity_hash == identity_hash)
        ).scalar_one()
    ledger.close()
    assert count == 1


@pytest.mark.integration
def test_concurrent_rotate_version_allocates_unique_version_numbers(pg_url: str) -> None:
    worker_count = 4
    identity_hash = f"hash-rotate-{uuid4().hex}"
    ref = RawObjectRef(
        source_name="test",
        dataset_name="test_ds",
        identity_hash=identity_hash,
        identity_key={"k": "concurrent-rotate"},
        update_mode=UpdateMode.MUTABLE,
    )
    start = Barrier(worker_count)
    errors: list[BaseException] = []
    version_numbers: list[int] = []

    def worker(index: int) -> None:
        ledger = RawObjectLedger(ledger_url=pg_url)
        try:
            start.wait(timeout=5)
            with ledger.transaction() as tx:
                result = tx.writer.rotate_version(
                    ref=ref,
                    source_url=f"https://example.com/v{index}",
                    fetched_at=datetime.now(UTC),
                    revalidation=RevalidationMetadata(etag=f'"v{index}"'),
                    sha256=f"{index}" * 64,
                    local_path=f"/tmp/v{index}",
                    storage_encoding="csv",
                )
                version_numbers.append(result.version.version_number)
        except BaseException as exc:  # pragma: no cover - surfaced through assertion below
            errors.append(exc)
        finally:
            ledger.close()

    threads = [Thread(target=worker, args=(index,)) for index in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert all(thread.is_alive() is False for thread in threads)
    assert sorted(version_numbers) == list(range(1, worker_count + 1))

    ledger = RawObjectLedger(ledger_url=pg_url)
    with ledger._engine.begin() as con:
        rows = con.execute(
            select(raw_object_versions.c.version_number)
            .join(raw_objects, raw_object_versions.c.raw_object_id == raw_objects.c.id)
            .where(raw_objects.c.identity_hash == identity_hash)
            .order_by(raw_object_versions.c.version_number)
        ).all()
    ledger.close()
    assert [row[0] for row in rows] == list(range(1, worker_count + 1))
