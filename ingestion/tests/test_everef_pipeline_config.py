from __future__ import annotations

import pytest

from eve_market_ingestion.pipelines import everef


def test_filesystem_destination_uses_local_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(everef.BUCKET_URL_ENV_VAR, raising=False)
    monkeypatch.delenv(everef.DATA_ROOT_ENV_VAR, raising=False)
    monkeypatch.setattr(
        everef,
        "filesystem",
        lambda bucket_url: {"bucket_url": bucket_url},
    )

    destination_config = everef.build_destination_config("filesystem")

    assert destination_config == {"bucket_url": everef.local_bucket_url()}
    assert destination_config["bucket_url"].startswith("file://")
    assert destination_config["bucket_url"].endswith(
        "/ingestion/.local/dlt-staging/everef/market_history"
    )


def test_filesystem_destination_uses_env_bucket_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(everef.BUCKET_URL_ENV_VAR, "file:///mnt/env")
    monkeypatch.setattr(
        everef,
        "filesystem",
        lambda bucket_url: {"bucket_url": bucket_url},
    )

    assert everef.build_destination_config("filesystem") == {"bucket_url": "file:///mnt/env"}


def test_filesystem_destination_cli_bucket_url_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(everef.BUCKET_URL_ENV_VAR, "file:///mnt/env")
    monkeypatch.setattr(
        everef,
        "filesystem",
        lambda bucket_url: {"bucket_url": bucket_url},
    )

    assert everef.build_destination_config("filesystem", "file:///mnt/cli") == {
        "bucket_url": "file:///mnt/cli"
    }


def test_filesystem_destination_rejects_empty_cli_bucket_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(everef.BUCKET_URL_ENV_VAR, "file:///mnt/env")

    with pytest.raises(ValueError, match="bucket_url must not be empty"):
        everef.build_destination_config("filesystem", "")


def test_filesystem_destination_rejects_empty_env_bucket_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(everef.BUCKET_URL_ENV_VAR, "")

    with pytest.raises(ValueError, match=everef.BUCKET_URL_ENV_VAR):
        everef.build_destination_config("filesystem")


def test_filesystem_destination_uses_mounted_storage_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(everef.BUCKET_URL_ENV_VAR, raising=False)
    monkeypatch.delenv(everef.DATA_ROOT_ENV_VAR, raising=False)
    monkeypatch.setattr(
        everef,
        "filesystem",
        lambda bucket_url: {"bucket_url": bucket_url},
    )

    assert everef.build_destination_config(
        "filesystem",
        storage_target="mounted",
    ) == {
        "bucket_url": "file:///opt/eve-market/data/dlt-staging/everef/market_history"
    }


def test_filesystem_destination_uses_configured_mounted_data_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(everef.BUCKET_URL_ENV_VAR, raising=False)
    monkeypatch.delenv(everef.DATA_ROOT_ENV_VAR, raising=False)
    monkeypatch.setattr(
        everef,
        "filesystem",
        lambda bucket_url: {"bucket_url": bucket_url},
    )

    assert everef.build_destination_config(
        "filesystem",
        storage_target="mounted",
        data_root="/mnt/eve-market",
    ) == {
        "bucket_url": "file:///mnt/eve-market/dlt-staging/everef/market_history"
    }


def test_filesystem_destination_uses_env_mounted_data_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(everef.BUCKET_URL_ENV_VAR, raising=False)
    monkeypatch.setenv(everef.DATA_ROOT_ENV_VAR, "/mnt/env-root")
    monkeypatch.setattr(
        everef,
        "filesystem",
        lambda bucket_url: {"bucket_url": bucket_url},
    )

    assert everef.build_destination_config(
        "filesystem",
        storage_target="mounted",
    ) == {
        "bucket_url": "file:///mnt/env-root/dlt-staging/everef/market_history"
    }


def test_filesystem_destination_data_root_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(everef.BUCKET_URL_ENV_VAR, raising=False)
    monkeypatch.setenv(everef.DATA_ROOT_ENV_VAR, "/mnt/env-root")
    monkeypatch.setattr(
        everef,
        "filesystem",
        lambda bucket_url: {"bucket_url": bucket_url},
    )

    assert everef.build_destination_config(
        "filesystem",
        storage_target="mounted",
        data_root="/mnt/arg-root",
    ) == {
        "bucket_url": "file:///mnt/arg-root/dlt-staging/everef/market_history"
    }


def test_filesystem_destination_rejects_empty_data_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(everef.BUCKET_URL_ENV_VAR, raising=False)
    monkeypatch.setenv(everef.DATA_ROOT_ENV_VAR, "/mnt/env-root")

    with pytest.raises(ValueError, match="data_root must not be empty"):
        everef.build_destination_config(
            "filesystem",
            storage_target="mounted",
            data_root="",
        )


def test_filesystem_destination_rejects_empty_env_data_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(everef.BUCKET_URL_ENV_VAR, raising=False)
    monkeypatch.setenv(everef.DATA_ROOT_ENV_VAR, "")

    with pytest.raises(ValueError, match=everef.DATA_ROOT_ENV_VAR):
        everef.build_destination_config("filesystem", storage_target="mounted")


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


def everef_cli_parser():
    from eve_market_ingestion.cli import build_parser

    return build_parser()
