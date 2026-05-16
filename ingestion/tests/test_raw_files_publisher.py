from __future__ import annotations

import hashlib
from pathlib import Path

from conftest import FakeHttpClient, NoValidatorHttpClient, raw_files_config
from ingest.raw_files.config import RawFilesConfig, sqlite_ledger_url
from ingest.raw_files.publisher import RawFileSpec, publish_raw_file
from ingest.raw_files.repository import RawFileRepository


def test_publish_raw_file_downloads_file_and_records_sqlite_ledger(
    tmp_path: Path,
) -> None:
    config = raw_files_config(tmp_path)
    client = FakeHttpClient(b"raw bytes")

    record = publish_raw_file(
        _spec(content_length=9), config=config, http_client=client
    )

    assert record.status == "downloaded"
    assert record.local_path is not None
    assert Path(record.local_path).read_bytes() == b"raw bytes"
    assert record.sha256 == hashlib.sha256(b"raw bytes").hexdigest()
    assert record.downloaded_size == len(b"raw bytes")
    assert client.get_calls == [record.source_url]


def test_publish_raw_file_uses_cache_hit_for_unchanged_file(tmp_path: Path) -> None:
    config = raw_files_config(tmp_path)
    client = FakeHttpClient(b"raw bytes")
    spec = _spec(content_length=9)

    first = publish_raw_file(spec, config=config, http_client=client)
    second = publish_raw_file(spec, config=config, http_client=client)

    assert first.local_path == second.local_path
    assert first.sha256 == second.sha256
    assert len(client.get_calls) == 1


def test_publish_raw_file_redownloads_when_remote_metadata_changes(
    tmp_path: Path,
) -> None:
    config = raw_files_config(tmp_path)
    client = FakeHttpClient(b"raw bytes")

    first = publish_raw_file(_spec(content_length=9), config=config, http_client=client)
    client.content = b"changed bytes"
    second = publish_raw_file(
        _spec(content_length=13, last_modified="2025-01-02T12:00:00+00:00"),
        config=config,
        http_client=client,
    )

    assert first.local_path != second.local_path
    assert first.sha256 != second.sha256
    assert len(client.get_calls) == 2


def test_publish_raw_file_uses_totals_count_as_change_detector(tmp_path: Path) -> None:
    config = raw_files_config(tmp_path)
    client = FakeHttpClient(b"raw bytes")
    spec = _spec(
        content_length=None, last_modified=None, etag=None, source_row_count=42
    )

    first = publish_raw_file(spec, config=config, http_client=client)
    second = publish_raw_file(spec, config=config, http_client=client)

    assert first.local_path == second.local_path
    assert len(client.get_calls) == 1


def test_publish_raw_file_prunes_old_changed_copies_by_default(tmp_path: Path) -> None:
    config = raw_files_config(tmp_path)
    client = FakeHttpClient(b"raw bytes 0")
    records = []

    for index in range(6):
        client.content = f"raw bytes {index}".encode()
        records.append(
            publish_raw_file(
                _spec(
                    content_length=len(client.content),
                    last_modified=f"2025-01-01T12:00:0{index}+00:00",
                ),
                config=config,
                http_client=client,
            )
        )

    assert records[0].local_path is not None
    assert not Path(records[0].local_path).exists()
    for record in records[1:]:
        assert record.local_path is not None
        assert Path(record.local_path).exists()

    repository = RawFileRepository(config.ledger_url)
    cached_records = repository.list_successes_for_source_date(
        source_name="source",
        dataset_name="dataset",
        source_date="2025-01-01",
    )
    assert {record.local_path for record in cached_records} == {
        record.local_path for record in records[1:]
    }


def test_publish_raw_file_prunes_old_changed_copies_per_date(tmp_path: Path) -> None:
    config = raw_files_config(tmp_path)
    client = FakeHttpClient(b"raw bytes 0")
    records_by_date = {"2025-01-01": [], "2025-01-02": []}

    for source_date, records in records_by_date.items():
        for index in range(6):
            client.content = f"raw bytes {source_date} {index}".encode()
            records.append(
                publish_raw_file(
                    _spec(
                        source_date=source_date,
                        cache_date=source_date,
                        content_length=len(client.content),
                        last_modified=f"2025-01-01T12:00:0{index}+00:00",
                    ),
                    config=config,
                    http_client=client,
                )
            )

    repository = RawFileRepository(config.ledger_url)
    for source_date, records in records_by_date.items():
        assert records[0].local_path is not None
        assert not Path(records[0].local_path).exists()
        for record in records[1:]:
            assert record.local_path is not None
            assert Path(record.local_path).exists()
        cached_records = repository.list_successes_for_source_date(
            source_name="source",
            dataset_name="dataset",
            source_date=source_date,
        )
        assert {record.local_path for record in cached_records} == {
            record.local_path for record in records[1:]
        }


def test_publish_raw_file_keeps_all_changed_copies_when_pruning_disabled(
    tmp_path: Path,
) -> None:
    config = RawFilesConfig(
        raw_root=tmp_path / "raw",
        ledger_url=sqlite_ledger_url(tmp_path / "raw" / "raw_files.sqlite"),
        max_copies_per_date=0,
    )
    client = FakeHttpClient(b"raw bytes 0")
    records = []

    for index in range(6):
        client.content = f"raw bytes {index}".encode()
        records.append(
            publish_raw_file(
                _spec(
                    content_length=len(client.content),
                    last_modified=f"2025-01-01T12:00:0{index}+00:00",
                ),
                config=config,
                http_client=client,
            )
        )

    for record in records:
        assert record.local_path is not None
        assert Path(record.local_path).exists()


def test_publish_raw_file_prunes_old_copies_on_cache_hit(tmp_path: Path) -> None:
    disabled_config = RawFilesConfig(
        raw_root=tmp_path / "raw",
        ledger_url=sqlite_ledger_url(tmp_path / "raw" / "raw_files.sqlite"),
        max_copies_per_date=0,
    )
    client = FakeHttpClient(b"raw bytes 0")
    records = []

    for index in range(3):
        client.content = f"raw bytes {index}".encode()
        records.append(
            publish_raw_file(
                _spec(
                    content_length=len(client.content),
                    last_modified=f"2025-01-01T12:00:0{index}+00:00",
                ),
                config=disabled_config,
                http_client=client,
            )
        )

    pruning_config = RawFilesConfig(
        raw_root=disabled_config.raw_root,
        ledger_url=disabled_config.ledger_url,
        max_copies_per_date=2,
    )
    cache_hit = publish_raw_file(
        _spec(
            content_length=len(client.content),
            last_modified="2025-01-01T12:00:02+00:00",
        ),
        config=pruning_config,
        http_client=client,
    )

    assert cache_hit.local_path == records[-1].local_path
    assert records[0].local_path is not None
    assert not Path(records[0].local_path).exists()
    for record in records[1:]:
        assert record.local_path is not None
        assert Path(record.local_path).exists()
    assert len(client.get_calls) == 3


def test_publish_raw_file_replaces_corrupt_existing_hash_path(tmp_path: Path) -> None:
    config = raw_files_config(tmp_path)
    content = b"raw bytes"
    digest = hashlib.sha256(content).hexdigest()
    corrupt_path = (
        config.raw_root
        / "source/dataset/date=2025-01-01"
        / f"sha256={digest}"
        / "file.csv.bz2"
    )
    corrupt_path.parent.mkdir(parents=True)
    corrupt_path.write_bytes(b"corrupt")

    record = publish_raw_file(
        _spec(content_length=len(content)),
        config=config,
        http_client=FakeHttpClient(content),
    )

    assert record.local_path == str(corrupt_path)
    assert corrupt_path.read_bytes() == content


def test_publish_raw_file_redownloads_when_cached_file_is_corrupt(
    tmp_path: Path,
) -> None:
    config = raw_files_config(tmp_path)
    client = FakeHttpClient(b"raw bytes")
    spec = _spec(content_length=9)

    first = publish_raw_file(spec, config=config, http_client=client)
    assert first.local_path is not None
    Path(first.local_path).write_bytes(b"corrupt")
    second = publish_raw_file(spec, config=config, http_client=client)

    assert second.local_path == first.local_path
    assert Path(second.local_path).read_bytes() == b"raw bytes"
    assert len(client.get_calls) == 2


def test_publish_raw_file_redownloads_when_source_has_no_validators(
    tmp_path: Path,
) -> None:
    config = raw_files_config(tmp_path)
    client = NoValidatorHttpClient(b"raw bytes")
    spec = _spec(content_length=None, last_modified=None, etag=None)

    first = publish_raw_file(spec, config=config, http_client=client)
    second = publish_raw_file(spec, config=config, http_client=client)

    assert first.local_path == second.local_path
    assert len(client.get_calls) == 2


def test_publish_raw_file_records_failed_download(tmp_path: Path) -> None:
    config = raw_files_config(tmp_path)
    client = FakeHttpClient(b"raw bytes")
    client.content = b"short"

    try:
        publish_raw_file(_spec(content_length=999), config=config, http_client=client)
    except RuntimeError:
        pass

    rows = RawFileRepository(config.ledger_url).list_successes_for_source_date(
        source_name="source",
        dataset_name="dataset",
        source_date="2025-01-01",
    )
    assert rows == []


def _spec(
    *,
    source_date: str = "2025-01-01",
    cache_date: str = "2025-01-01",
    content_length: int | None = None,
    last_modified: str | None = "2025-01-01T12:00:00+00:00",
    etag: str | None = '"etag-1"',
    source_row_count: int | None = None,
) -> RawFileSpec:
    return RawFileSpec(
        source_name="source",
        dataset_name="dataset",
        source_date=source_date,
        source_url=f"https://example.test/{source_date}/file.csv.bz2",
        file_name="file.csv.bz2",
        cache_relative_parts=("source", "dataset", f"date={cache_date}"),
        content_length=content_length,
        last_modified=last_modified,
        etag=etag,
        source_row_count=source_row_count,
    )
