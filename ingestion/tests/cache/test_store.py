from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ingest.cache import Cache, CacheObject, UpdateMode
from ingest.cache.models import CacheResultStatus, FetchOutcome, FetchResult
from tests.cache.fakes import InMemoryRawObjectLedger


class FakeClient:
    def __init__(self, responses: list[FetchResult]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str], str]] = []
        self.closed = False

    def read(
        self,
        *,
        source_url: str,
        request_headers: dict[str, str],
        temp_path: str,
    ) -> FetchResult:
        self.calls.append((source_url, request_headers, temp_path))
        response = self.responses.pop(0)
        if (
            response.outcome is FetchOutcome.DOWNLOADED
            and response.temp_path is not None
        ):
            Path(response.temp_path).parent.mkdir(parents=True, exist_ok=True)
            Path(response.temp_path).write_bytes(b"payload")
        return response

    def close(self) -> None:
        self.closed = True


class SequenceClient:
    def __init__(self, clients: list[FakeClient]) -> None:
        self.clients = list(clients)
        self._all_clients = list(clients)
        self.closed = False

    def read(
        self,
        *,
        source_url: str,
        request_headers: dict[str, str],
        temp_path: str,
    ) -> FetchResult:
        if not self.clients:
            raise AssertionError("No fake clients remain")
        client = self.clients[0]
        result = client.read(
            source_url=source_url,
            request_headers=request_headers,
            temp_path=temp_path,
        )
        if not client.responses:
            self.clients.pop(0)
        return result

    def close(self) -> None:
        self.closed = True
        for client in self._all_clients:
            client.close()


def _store(
    *,
    tmp_path: Path,
    client: FakeClient | SequenceClient,
    dataset_name: str = "market-orders",
    update_mode: UpdateMode = UpdateMode.SNAPSHOT,
    source_name: str = "everef",
    ledger: InMemoryRawObjectLedger | None = None,
) -> Cache:
    return Cache(
        dataset_name=dataset_name,
        update_mode=update_mode,
        source_name=source_name,
        raw_root=str(tmp_path / "raw"),
        client=client,
        ledger=ledger or InMemoryRawObjectLedger(),
    )


def _response(
    *,
    tmp_path: Path,
    outcome: FetchOutcome,
    name: str,
    etag: str | None = None,
    last_modified: str | None = None,
    fetched_at: datetime | None = None,
    sha256: str = "abc123",
) -> FetchResult:
    return FetchResult(
        outcome=outcome,
        fetched_at=fetched_at or datetime.now(UTC),
        etag=etag,
        last_modified=last_modified,
        content_length=7,
        temp_path=(
            str(tmp_path / f"{name}.download")
            if outcome is FetchOutcome.DOWNLOADED
            else None
        ),
        sha256=(sha256 if outcome is FetchOutcome.DOWNLOADED else None),
    )


@pytest.mark.parametrize(
    ("dataset_name", "update_mode", "source_url", "expected_identity"),
    [
        (
            "market-orders",
            UpdateMode.SNAPSHOT,
            "https://data.everef.net/market-orders/history/2026/2026-01-01/file.csv.bz2",
            {"source_path": "market-orders/history/2026/2026-01-01/file.csv.bz2"},
        ),
        (
            "market-history",
            UpdateMode.MUTABLE,
            "https://data.everef.net/market-history/2026-01-01.csv.bz2",
            {"source_path": "market-history/2026-01-01.csv.bz2"},
        ),
    ],
)
def test_get_defaults_identity_to_source_relative_path(
    tmp_path: Path,
    dataset_name: str,
    update_mode: UpdateMode,
    source_url: str,
    expected_identity: dict[str, str],
) -> None:
    client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="default-identity",
            )
        ]
    )

    with _store(
        tmp_path=tmp_path,
        client=client,
        dataset_name=dataset_name,
        update_mode=update_mode,
    ) as store:
        result = store.get(CacheObject(source_url=source_url))

    assert result.identity_key == expected_identity
    assert result.path == result.version.local_path
    assert result.update_mode is update_mode
    assert result.changed is True


def test_get_changed_returns_changed_objects(tmp_path: Path) -> None:
    client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="batch-first",
                etag='"etag-1"',
            ),
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.NOT_MODIFIED,
                name="batch-second",
                etag='"etag-1"',
            ),
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="batch-third",
                etag='"etag-2"',
            ),
        ]
    )
    first_object = CacheObject(
        source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/file.csv.bz2"
    )
    second_object = CacheObject(
        source_url="https://data.everef.net/market-orders/history/2026/2026-01-02/file.csv.bz2"
    )

    with _store(tmp_path=tmp_path, client=client) as store:
        store.get_all([first_object])
        changed_results = store.get_changed([first_object, second_object])

    assert len(changed_results) == 1
    assert changed_results[0].identity_key == {
        "source_path": "market-orders/history/2026/2026-01-02/file.csv.bz2"
    }
    assert changed_results[0].changed is True


def test_get_uses_explicit_source_path_for_non_everef_url(tmp_path: Path) -> None:
    client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="explicit-source-path",
            )
        ]
    )

    with _store(tmp_path=tmp_path, client=client, source_name="example") as store:
        result = store.get(
            CacheObject(
                source_url="https://example.com/downloads/file.csv",
                source_path="vendor/market-orders/file.csv",
            )
        )

    assert result.identity_key == {"source_path": "vendor/market-orders/file.csv"}
    assert result.path == str(
        tmp_path / "raw" / "example" / "vendor" / "market-orders" / "file.csv"
    )


def test_get_reuses_existing_snapshot_without_remote_read(tmp_path: Path) -> None:
    first_client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="snapshot-first",
            )
        ]
    )
    with _store(tmp_path=tmp_path, client=first_client) as store:
        first_result = store.get(
            CacheObject(
                source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/file.csv.bz2",
            )
        )

        second_result = store.get(
            CacheObject(
                source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/file.csv.bz2",
            )
        )

    assert first_result.status is CacheResultStatus.STORED
    assert second_result.status is CacheResultStatus.HIT
    assert first_result.changed is True
    assert second_result.changed is False
    assert second_result.version.local_path == first_result.version.local_path
    assert first_client.calls == [
        (
            "https://data.everef.net/market-orders/history/2026/2026-01-01/file.csv.bz2",
            {},
            first_client.calls[0][2],
        )
    ]


def test_get_rejects_update_mode_mismatch(tmp_path: Path) -> None:
    ledger = InMemoryRawObjectLedger()
    client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="update-mode-mismatch",
            )
        ]
    )

    with _store(tmp_path=tmp_path, client=client, ledger=ledger) as store:
        store.get(
            CacheObject(
                source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/file.csv.bz2",
            )
        )

    with _store(
        tmp_path=tmp_path,
        client=FakeClient([]),
        dataset_name="market-orders",
        update_mode=UpdateMode.MUTABLE,
        ledger=ledger,
    ) as store:
        with pytest.raises(ValueError, match="update_mode mismatch"):
            store.get(
                CacheObject(
                    source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/file.csv.bz2",
                )
            )


def test_get_uses_conditional_headers_for_mutable_files(tmp_path: Path) -> None:
    first_client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="mutable-first",
                etag='"etag-1"',
            )
        ]
    )
    identity_key = {"source_date": "2026-01-01"}
    second_client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.NOT_MODIFIED,
                name="mutable-second",
                etag='"etag-1"',
            )
        ]
    )

    with _store(
        tmp_path=tmp_path,
        client=SequenceClient([first_client, second_client]),
        dataset_name="market-history",
        update_mode=UpdateMode.MUTABLE,
    ) as store:
        first_result = store.get(
            CacheObject(
                source_url="https://data.everef.net/market-history/2026-01-01.csv.bz2",
                identity_key=identity_key,
            )
        )
        result = store.get(
            CacheObject(
                source_url="https://data.everef.net/market-history/2026-01-01.csv.bz2",
                identity_key=identity_key,
            )
        )

    assert result.status is CacheResultStatus.HIT
    assert result.changed is False
    assert "etag" not in Path(first_result.path).name
    assert first_client.calls[0][1] == {}
    assert second_client.calls[0][1] == {"If-None-Match": '"etag-1"'}


def test_get_uses_stored_revalidation_metadata_not_version_fields(
    tmp_path: Path,
) -> None:
    ledger = InMemoryRawObjectLedger()
    first_client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="mutable-seed",
                etag='"etag-1"',
            )
        ]
    )
    second_client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.NOT_MODIFIED,
                name="mutable-revalidate",
                etag='"etag-1"',
            )
        ]
    )
    identity_key = {"source_date": "2026-01-01"}

    with _store(
        tmp_path=tmp_path,
        client=SequenceClient([first_client, second_client]),
        dataset_name="market-history",
        update_mode=UpdateMode.MUTABLE,
        ledger=ledger,
    ) as store:
        first_result = store.get(
            CacheObject(
                source_url="https://data.everef.net/market-history/2026-01-01.csv.bz2",
                identity_key=identity_key,
            )
        )
        ledger._versions_by_object_id[first_result.raw_object.id] = [
            replace(first_result.version, etag='"wrong-version-etag"')
        ]

        result = store.get(
            CacheObject(
                source_url="https://data.everef.net/market-history/2026-01-01.csv.bz2",
                identity_key=identity_key,
            )
        )

    assert result.status is CacheResultStatus.HIT
    assert second_client.calls[0][1] == {"If-None-Match": '"etag-1"'}


def test_get_rereads_when_not_modified_but_local_file_missing(tmp_path: Path) -> None:
    identity_key = {"source_date": "2026-01-01"}
    seeded_client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="seed",
                etag='"etag-1"',
            )
        ]
    )

    next_client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.NOT_MODIFIED,
                name="missing-local-first",
                etag='"etag-1"',
            ),
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="missing-local-second",
                etag='"etag-1"',
            ),
        ]
    )

    with _store(
        tmp_path=tmp_path,
        client=SequenceClient([seeded_client, next_client]),
        dataset_name="market-history",
        update_mode=UpdateMode.MUTABLE,
    ) as store:
        seeded_result = store.get(
            CacheObject(
                source_url="https://data.everef.net/market-history/2026-01-01.csv.bz2",
                identity_key=identity_key,
            )
        )

        Path(seeded_result.version.local_path).unlink()
        result = store.get(
            CacheObject(
                source_url="https://data.everef.net/market-history/2026-01-01.csv.bz2",
                identity_key=identity_key,
            )
        )

    assert result.status is CacheResultStatus.STORED
    assert next_client.calls[0][1] == {"If-None-Match": '"etag-1"'}
    assert next_client.calls[1][1] == {}
    assert Path(result.version.local_path).exists()


def test_get_keeps_one_current_mutable_copy_per_logical_object(tmp_path: Path) -> None:
    identity_key = {"source_date": "2026-01-01"}
    client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="one",
                etag='"etag-1"',
                fetched_at=datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
                sha256="sha-one",
            ),
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="two",
                etag='"etag-2"',
                fetched_at=datetime(2026, 1, 1, 2, 0, tzinfo=UTC),
                sha256="sha-two",
            ),
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="three",
                etag='"etag-3"',
                fetched_at=datetime(2026, 1, 1, 3, 0, tzinfo=UTC),
                sha256="sha-three",
            ),
        ]
    )

    with _store(
        tmp_path=tmp_path,
        client=client,
        dataset_name="market-history",
        update_mode=UpdateMode.MUTABLE,
    ) as store:
        result = None
        for _ in range(3):
            result = store.get(
                CacheObject(
                    source_url="https://data.everef.net/market-history/2026-01-01.csv.bz2",
                    identity_key=identity_key,
                )
            )

    assert result is not None
    assert result.version.etag == '"etag-3"'
    object_files = list(
        (tmp_path / "raw" / "everef" / "market-history" / "objects").rglob("*.bz2")
    )
    assert len(object_files) == 1
    assert object_files[0] == Path(result.version.local_path)


def test_get_unpublished_includes_snapshot_hits_until_mark_published_many(
    tmp_path: Path,
) -> None:
    ledger = InMemoryRawObjectLedger()
    client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="publish-first",
                sha256="sha-first",
            ),
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="publish-second",
                sha256="sha-second",
            ),
        ]
    )
    first_object = CacheObject(
        source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/file.csv.bz2"
    )
    second_object = CacheObject(
        source_url="https://data.everef.net/market-orders/history/2026/2026-01-02/file.csv.bz2"
    )

    with _store(tmp_path=tmp_path, client=client, ledger=ledger) as store:
        store.get_all([first_object])
        unpublished_results = store.get_unpublished([first_object, second_object])
        store.mark_published_many(
            unpublished_results,
            publication_scope="raw-market-history",
            publisher_run_id="run-1",
        )
        filtered_results = store.get_unpublished([first_object, second_object])

    assert len(unpublished_results) == 2
    assert unpublished_results[0].status is CacheResultStatus.HIT
    assert unpublished_results[0].identity_key == {
        "source_path": "market-orders/history/2026/2026-01-01/file.csv.bz2"
    }
    assert unpublished_results[1].identity_key == {
        "source_path": "market-orders/history/2026/2026-01-02/file.csv.bz2"
    }
    assert filtered_results == []
    assert ledger.resolve_fetch_plans_calls >= 2
    assert ledger.filter_published_calls >= 2


def test_snapshot_hit_without_ledger_state_redownloads(tmp_path: Path) -> None:
    client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="missing-ledger-first",
                fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="missing-ledger-second",
                fetched_at=datetime(2026, 1, 2, tzinfo=UTC),
                sha256="def456",
            ),
        ]
    )
    first_store = _store(tmp_path=tmp_path, client=client)
    second_store = _store(
        tmp_path=tmp_path, client=client, ledger=InMemoryRawObjectLedger()
    )
    cache_object = CacheObject(
        source_url="https://data.everef.net/market-orders/history/2026/2026-01-01/file.csv.bz2"
    )

    with first_store as store:
        first_result = store.get(cache_object)

    assert Path(first_result.path).exists()

    with second_store as store:
        second_result = store.get(cache_object)

    assert len(client.calls) == 2
    assert second_result.changed is True
    assert second_result.version.sha256 == "def456"


def test_mark_published_is_idempotent(tmp_path: Path) -> None:
    client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="publish-idempotent",
            )
        ]
    )

    with _store(
        tmp_path=tmp_path,
        client=client,
        dataset_name="market-history",
        update_mode=UpdateMode.MUTABLE,
    ) as store:
        result = store.get(
            CacheObject(
                source_url="https://data.everef.net/market-history/2026-01-01.csv.bz2",
            )
        )
        store.mark_published(result)
        store.mark_published(result)

        assert store.is_published(result) is True


def test_store_rejects_non_postgres_ledger_urls(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ledger_url must be a PostgreSQL URL"):
        Cache(
            dataset_name="market-orders",
            update_mode=UpdateMode.SNAPSHOT,
            raw_root=str(tmp_path / "raw"),
            ledger_url=f"sqlite:///{tmp_path / 'raw_files.sqlite'}",
            client=FakeClient([]),
        )


def test_store_rejects_query_string_urls(tmp_path: Path) -> None:
    store = _store(tmp_path=tmp_path, client=FakeClient([]))

    with store:
        with pytest.raises(
            ValueError, match="must not include query strings or fragments"
        ):
            store.get(
                CacheObject(source_url="https://data.everef.net/file.csv.bz2?token=abc")
            )


@pytest.mark.parametrize(
    "source_url",
    ["file:///tmp/file.csv.bz2", "https:///file.csv.bz2"],
)
def test_store_rejects_invalid_http_source_urls(
    tmp_path: Path, source_url: str
) -> None:
    store = _store(tmp_path=tmp_path, client=FakeClient([]))

    with store:
        with pytest.raises(
            ValueError, match="must be an http or https URL with a host"
        ):
            store.get(CacheObject(source_url=source_url))


def test_store_accepts_non_everef_hosts_and_uncompressed_paths(tmp_path: Path) -> None:
    client = FakeClient(
        [
            _response(
                tmp_path=tmp_path,
                outcome=FetchOutcome.DOWNLOADED,
                name="generic-host",
            )
        ]
    )

    with _store(tmp_path=tmp_path, client=client, source_name="other") as store:
        result = store.get(CacheObject(source_url="https://example.com/file.csv"))

    assert result.raw_object.source_name == "other"
    assert result.identity_key == {"source_path": "file.csv"}
