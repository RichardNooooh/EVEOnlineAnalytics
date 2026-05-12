from __future__ import annotations

from pathlib import Path

import pytest

from ingest.raw_files.config import (
    MOUNTED_STORAGE_TARGET,
    RAW_FILES_DB_ENV_VAR,
    RAW_FILES_MAX_COPIES_PER_DATE_ENV_VAR,
    RAW_FILES_ROOT_ENV_VAR,
    resolve_raw_files_config,
)


def test_raw_files_config_resolves_local_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RAW_FILES_ROOT_ENV_VAR, raising=False)
    monkeypatch.delenv(RAW_FILES_DB_ENV_VAR, raising=False)

    config = resolve_raw_files_config()

    assert str(config.raw_root).endswith("/ingestion/.local/raw")
    assert config.db_path == config.raw_root / "raw_files.sqlite"
    assert config.max_copies_per_date == 5


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
    monkeypatch.setenv(RAW_FILES_MAX_COPIES_PER_DATE_ENV_VAR, "0")

    config = resolve_raw_files_config()

    assert config.raw_root == tmp_path / "env-raw"
    assert config.db_path == tmp_path / "env.sqlite"
    assert config.max_copies_per_date == 0


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
