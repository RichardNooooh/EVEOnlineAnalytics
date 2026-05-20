from __future__ import annotations

from pathlib import Path

import pytest

from ingest.raw_files.config import (
    MOUNTED_STORAGE_TARGET,
    resolve_raw_files_config,
    sqlite_ledger_url,
)


def test_raw_files_config_resolves_local_default() -> None:
    config = resolve_raw_files_config()

    assert str(config.raw_root).endswith("/ingestion/.local/raw")
    assert config.ledger_url == sqlite_ledger_url(config.raw_root / "raw_files.sqlite")
    assert config.max_copies_per_date == 5


def test_raw_files_config_rejects_mounted_target_without_ledger_url(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="mounted raw-file storage requires an explicit ledger URL.*PostgreSQL",
    ):
        resolve_raw_files_config(
            storage_target=MOUNTED_STORAGE_TARGET,
            data_root=str(tmp_path / "data"),
        )


def test_raw_files_config_resolves_mounted_target_with_explicit_ledger_url(
    tmp_path: Path,
) -> None:
    config = resolve_raw_files_config(
        storage_target=MOUNTED_STORAGE_TARGET,
        data_root=str(tmp_path / "data"),
        ledger_url="postgresql://ledger.test/raw",
    )

    assert config.raw_root == tmp_path / "data" / "raw"
    assert config.ledger_url == "postgresql://ledger.test/raw"


def test_raw_files_config_allows_local_raw_root_with_mounted_storage_target(
    tmp_path: Path,
) -> None:
    config = resolve_raw_files_config(
        raw_root=str(tmp_path / "raw"),
        storage_target=MOUNTED_STORAGE_TARGET,
        data_root=str(tmp_path / "data"),
    )

    assert config.raw_root == tmp_path / "raw"
    assert config.ledger_url == sqlite_ledger_url(config.raw_root / "raw_files.sqlite")


def test_raw_files_config_rejects_mounted_raw_root_without_ledger_url(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="mounted raw-file storage requires an explicit ledger URL.*PostgreSQL",
    ):
        resolve_raw_files_config(
            raw_root=str(tmp_path / "data" / "raw-v2"),
            storage_target=MOUNTED_STORAGE_TARGET,
            data_root=str(tmp_path / "data"),
        )


def test_raw_files_config_accepts_explicit_ledger_url(tmp_path: Path) -> None:
    config = resolve_raw_files_config(
        raw_root=str(tmp_path / "raw"),
        ledger_url="postgresql://ledger.test/raw",
    )

    assert config.ledger_url == "postgresql://ledger.test/raw"


def test_raw_files_config_rejects_path_ledger_url(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError, match="must be a sqlite, postgres, or postgresql URL"
    ):
        resolve_raw_files_config(
            raw_root=str(tmp_path / "raw"),
            ledger_url=str(tmp_path / "raw_files.sqlite"),
        )


def test_raw_files_config_accepts_explicit_max_copies(tmp_path: Path) -> None:
    config = resolve_raw_files_config(
        raw_root=str(tmp_path / "raw"),
        max_copies_per_date="7",
    )

    assert config.max_copies_per_date == 7


def test_raw_files_config_rejects_invalid_max_copies(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        resolve_raw_files_config(
            raw_root=str(tmp_path / "raw"),
            max_copies_per_date="-1",
        )
