from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ingest.raw_files.config import MOUNTED_STORAGE_TARGET
from ingest.raw_files.config import RawFilesConfig
from ingest.raw_files.config import RAW_FILES_DB_ENV_VAR
from ingest.raw_files.config import RAW_FILES_ROOT_ENV_VAR
from ingest.raw_files.config import resolve_raw_files_config
from ingest.raw_files.everef import acquire_everef_market_history_files
from ingest.raw_files.everef import (
    list_cached_everef_market_history_files,
)


class FakeHttpClient:
    def __init__(
        self, content: bytes, *, last_modified: str = "Wed, 01 Jan 2025 12:00:00 GMT"
    ) -> None:
        self.content = content
        self.last_modified = last_modified
        self.head_calls: list[str] = []
        self.get_calls: list[str] = []

    def head(self, url: str, *, allow_redirects: bool) -> FakeResponse:
        assert allow_redirects is True
        self.head_calls.append(url)
        return FakeResponse(
            200,
            headers={
                "content-length": str(len(self.content)),
                "last-modified": self.last_modified,
            },
        )

    def get(self, url: str, *, stream: bool) -> FakeResponse:
        assert stream is True
        self.get_calls.append(url)
        return FakeResponse(200, content=self.content)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content

    def iter_content(self, *, chunk_size: int):
        yield self.content[:chunk_size]
        yield self.content[chunk_size:]

    def close(self) -> None:
        return None


class NoValidatorHttpClient(FakeHttpClient):
    def head(self, url: str, *, allow_redirects: bool) -> FakeResponse:
        assert allow_redirects is True
        self.head_calls.append(url)
        return FakeResponse(200)


def test_acquire_downloads_file_and_records_sqlite_ledger(tmp_path: Path) -> None:
    config = _config(tmp_path)
    client = FakeHttpClient(b"raw bytes")

    records = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
    )

    assert len(records) == 1
    record = records[0]
    assert record.status == "downloaded"
    assert (
        record.source_url
        == "https://example.test/history/2025/market-history-2025-01-01.csv.bz2"
    )
    assert record.local_path is not None
    assert Path(record.local_path).read_bytes() == b"raw bytes"
    assert record.sha256 is not None
    assert record.downloaded_size == len(b"raw bytes")
    assert client.get_calls == [record.source_url]

    cached_items = list_cached_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
    )
    assert cached_items == [record.to_source_item()]


def test_acquire_uses_cache_hit_for_unchanged_file(tmp_path: Path) -> None:
    config = _config(tmp_path)
    client = FakeHttpClient(b"raw bytes")

    first = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
    )[0]
    second = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
    )[0]

    assert first.local_path == second.local_path
    assert first.sha256 == second.sha256
    assert len(client.head_calls) == 2
    assert len(client.get_calls) == 1


def test_acquire_redownloads_when_remote_metadata_changes(tmp_path: Path) -> None:
    config = _config(tmp_path)
    client = FakeHttpClient(b"raw bytes")

    first = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
    )[0]
    client.content = b"changed bytes"
    client.last_modified = "Thu, 02 Jan 2025 12:00:00 GMT"
    second = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
    )[0]

    assert first.local_path != second.local_path
    assert first.sha256 != second.sha256
    assert len(client.get_calls) == 2


def test_acquire_replaces_corrupt_existing_hash_path(tmp_path: Path) -> None:
    config = _config(tmp_path)
    content = b"raw bytes"
    digest = hashlib.sha256(content).hexdigest()
    corrupt_path = (
        config.raw_root
        / "everef/market-history"
        / "year=2025"
        / "date=2025-01-01"
        / f"sha256={digest}"
        / "market-history-2025-01-01.csv.bz2"
    )
    corrupt_path.parent.mkdir(parents=True)
    corrupt_path.write_bytes(b"corrupt")

    record = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=FakeHttpClient(content),
    )[0]

    assert record.local_path == str(corrupt_path)
    assert corrupt_path.read_bytes() == content


def test_acquire_redownloads_when_cached_file_is_corrupt(tmp_path: Path) -> None:
    config = _config(tmp_path)
    client = FakeHttpClient(b"raw bytes")

    first = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
    )[0]
    assert first.local_path is not None
    Path(first.local_path).write_bytes(b"corrupt")
    second = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
    )[0]

    assert second.local_path == first.local_path
    assert Path(second.local_path).read_bytes() == b"raw bytes"
    assert len(client.get_calls) == 2


def test_acquire_redownloads_when_source_has_no_validators(tmp_path: Path) -> None:
    config = _config(tmp_path)
    client = NoValidatorHttpClient(b"raw bytes")

    first = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
    )[0]
    second = acquire_everef_market_history_files(
        "2025-01-01",
        "2025-01-01",
        base_url="https://example.test/history",
        config=config,
        http_client=client,
    )[0]

    assert first.local_path == second.local_path
    assert len(client.get_calls) == 2


def test_list_cached_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not cached"):
        list_cached_everef_market_history_files(
            "2025-01-01",
            "2025-01-01",
            base_url="https://example.test/history",
            config=_config(tmp_path),
        )


def test_raw_files_config_resolves_local_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RAW_FILES_ROOT_ENV_VAR, raising=False)
    monkeypatch.delenv(RAW_FILES_DB_ENV_VAR, raising=False)

    config = resolve_raw_files_config()

    assert str(config.raw_root).endswith("/ingestion/.local/raw")
    assert config.db_path == config.raw_root / "raw_files.sqlite"


def test_raw_files_config_resolves_mounted_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RAW_FILES_ROOT_ENV_VAR, raising=False)
    monkeypatch.delenv(RAW_FILES_DB_ENV_VAR, raising=False)

    config = resolve_raw_files_config(
        storage_target=MOUNTED_STORAGE_TARGET,
        data_root=str(tmp_path / "data"),
    )

    assert config.raw_root == tmp_path / "data" / "raw"
    assert config.db_path == config.raw_root / "raw_files.sqlite"


def test_raw_files_config_resolves_env_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RAW_FILES_ROOT_ENV_VAR, str(tmp_path / "env-raw"))
    monkeypatch.setenv(RAW_FILES_DB_ENV_VAR, str(tmp_path / "env.sqlite"))

    config = resolve_raw_files_config()

    assert config.raw_root == tmp_path / "env-raw"
    assert config.db_path == tmp_path / "env.sqlite"


def _config(tmp_path: Path) -> RawFilesConfig:
    return RawFilesConfig(
        raw_root=tmp_path / "raw",
        db_path=tmp_path / "raw" / "raw_files.sqlite",
    )
