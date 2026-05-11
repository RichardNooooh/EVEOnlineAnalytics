from __future__ import annotations

import pytest

from eve_market_ingestion.pipelines import everef


class FakeDuckLakeCredentials:
    def __init__(self, name: str, *, catalog: str, storage: str) -> None:
        self.name = name
        self.catalog = catalog
        self.storage = storage


def fake_ducklake_destination(credentials: FakeDuckLakeCredentials) -> dict[str, object]:
    return {"credentials": credentials}


def patch_ducklake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(everef, "DuckLakeCredentials", FakeDuckLakeCredentials)
    monkeypatch.setattr(everef, "ducklake", fake_ducklake_destination)


def test_ducklake_destination_uses_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.delenv(everef.DUCKLAKE_NAME_ENV_VAR, raising=False)
    monkeypatch.delenv(everef.DUCKLAKE_CATALOG_ENV_VAR, raising=False)
    monkeypatch.delenv(everef.DUCKLAKE_STORAGE_ENV_VAR, raising=False)
    monkeypatch.delenv(everef.DATA_ROOT_ENV_VAR, raising=False)

    destination_config = everef.build_destination_config("ducklake")

    credentials = destination_config["credentials"]
    assert credentials.name == everef.DEFAULT_DUCKLAKE_NAME
    assert credentials.catalog == everef.local_ducklake_catalog()
    assert credentials.storage == everef.local_ducklake_storage()
    assert credentials.catalog.startswith("sqlite:///")
    assert credentials.catalog.endswith("/ingestion/.local/ducklake/everef_market_history/lake_catalog.sqlite")
    assert credentials.storage.startswith("file://")
    assert credentials.storage.endswith("/ingestion/.local/ducklake/everef_market_history/files")


def test_ducklake_destination_uses_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.setenv(everef.DUCKLAKE_NAME_ENV_VAR, "env_lake")
    monkeypatch.setenv(everef.DUCKLAKE_CATALOG_ENV_VAR, "postgresql://env/catalog")
    monkeypatch.setenv(everef.DUCKLAKE_STORAGE_ENV_VAR, "file:///mnt/env")

    destination_config = everef.build_destination_config("ducklake")

    credentials = destination_config["credentials"]
    assert credentials.name == "env_lake"
    assert credentials.catalog == "postgresql://env/catalog"
    assert credentials.storage == "file:///mnt/env"


def test_ducklake_destination_explicit_args_override_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.setenv(everef.DUCKLAKE_NAME_ENV_VAR, "env_lake")
    monkeypatch.setenv(everef.DUCKLAKE_CATALOG_ENV_VAR, "postgresql://env/catalog")
    monkeypatch.setenv(everef.DUCKLAKE_STORAGE_ENV_VAR, "file:///mnt/env")

    destination_config = everef.build_destination_config(
        "ducklake",
        "arg_lake",
        "postgresql://arg/catalog",
        "file:///mnt/arg",
    )

    credentials = destination_config["credentials"]
    assert credentials.name == "arg_lake"
    assert credentials.catalog == "postgresql://arg/catalog"
    assert credentials.storage == "file:///mnt/arg"


def test_ducklake_destination_uses_mounted_storage_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.delenv(everef.DUCKLAKE_STORAGE_ENV_VAR, raising=False)
    monkeypatch.delenv(everef.DATA_ROOT_ENV_VAR, raising=False)

    destination_config = everef.build_destination_config(
        "ducklake",
        storage_target="mounted",
    )

    credentials = destination_config["credentials"]
    assert credentials.storage == "file:///opt/eve-market/data/ducklake/everef/market_history"


def test_ducklake_destination_uses_data_root_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.delenv(everef.DUCKLAKE_STORAGE_ENV_VAR, raising=False)
    monkeypatch.setenv(everef.DATA_ROOT_ENV_VAR, "/mnt/env-root")

    destination_config = everef.build_destination_config(
        "ducklake",
        storage_target="mounted",
        data_root="/mnt/arg-root",
    )

    credentials = destination_config["credentials"]
    assert credentials.storage == "file:///mnt/arg-root/ducklake/everef/market_history"


def test_ducklake_storage_override_skips_mounted_data_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.setenv(everef.DATA_ROOT_ENV_VAR, "")

    destination_config = everef.build_destination_config(
        "ducklake",
        ducklake_storage="file:///mnt/explicit",
        storage_target="mounted",
    )

    credentials = destination_config["credentials"]
    assert credentials.storage == "file:///mnt/explicit"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"ducklake_name": ""}, "ducklake_name must not be empty"),
        ({"ducklake_catalog": ""}, "ducklake_catalog must not be empty"),
        ({"ducklake_storage": ""}, "ducklake_storage must not be empty"),
        ({"storage_target": "mounted", "data_root": ""}, "data_root must not be empty"),
    ],
)
def test_ducklake_destination_rejects_empty_explicit_values(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, str],
    message: str,
) -> None:
    patch_ducklake(monkeypatch)

    with pytest.raises(ValueError, match=message):
        everef.build_destination_config("ducklake", **kwargs)


@pytest.mark.parametrize(
    ("env_var", "message"),
    [
        (everef.DUCKLAKE_NAME_ENV_VAR, everef.DUCKLAKE_NAME_ENV_VAR),
        (everef.DUCKLAKE_CATALOG_ENV_VAR, everef.DUCKLAKE_CATALOG_ENV_VAR),
        (everef.DUCKLAKE_STORAGE_ENV_VAR, everef.DUCKLAKE_STORAGE_ENV_VAR),
    ],
)
def test_ducklake_destination_rejects_empty_env_values(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    message: str,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.setenv(env_var, "")

    with pytest.raises(ValueError, match=message):
        everef.build_destination_config("ducklake")


def test_ducklake_destination_rejects_empty_env_data_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.delenv(everef.DUCKLAKE_STORAGE_ENV_VAR, raising=False)
    monkeypatch.delenv(everef.DATA_ROOT_ENV_VAR, raising=False)
    monkeypatch.setenv(everef.DATA_ROOT_ENV_VAR, "")

    with pytest.raises(ValueError, match=everef.DATA_ROOT_ENV_VAR):
        everef.build_destination_config("ducklake", storage_target="mounted")


def test_non_ducklake_destination_returns_raw_string() -> None:
    assert everef.build_destination_config("filesystem") == "filesystem"


def test_cli_defaults_to_parquet_loader_format() -> None:
    parser = everef_cli_parser()

    args = parser.parse_args(
        [
            "everef-market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-01",
        ]
    )

    assert args.loader_file_format == "parquet"
    assert args.destination == "ducklake"
    assert args.storage_target == "local"
    assert args.data_root is None


def test_cli_accepts_mounted_storage_target() -> None:
    parser = everef_cli_parser()

    args = parser.parse_args(
        [
            "everef-market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-01",
            "--storage-target",
            "mounted",
        ]
    )

    assert args.storage_target == "mounted"


def test_cli_accepts_data_root() -> None:
    parser = everef_cli_parser()

    args = parser.parse_args(
        [
            "everef-market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-01",
            "--storage-target",
            "mounted",
            "--data-root",
            "/mnt/eve-market",
        ]
    )

    assert args.data_root == "/mnt/eve-market"


def test_cli_accepts_ducklake_name_catalog_storage() -> None:
    parser = everef_cli_parser()

    args = parser.parse_args(
        [
            "everef-market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-01",
            "--ducklake-name",
            "arg_lake",
            "--ducklake-catalog",
            "postgresql://arg/catalog",
            "--ducklake-storage",
            "file:///mnt/arg",
        ]
    )

    assert args.ducklake_name == "arg_lake"
    assert args.ducklake_catalog == "postgresql://arg/catalog"
    assert args.ducklake_storage == "file:///mnt/arg"


def everef_cli_parser():
    from eve_market_ingestion.cli import build_parser

    return build_parser()
