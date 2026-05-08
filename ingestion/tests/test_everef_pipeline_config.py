from __future__ import annotations

import pytest

from eve_market_ingestion.pipelines import everef


def test_filesystem_destination_requires_bucket_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(everef.BUCKET_URL_ENV_VAR, raising=False)

    with pytest.raises(ValueError, match="filesystem destination requires"):
        everef.build_destination_config("filesystem")


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


def everef_cli_parser():
    from eve_market_ingestion.cli import build_parser

    return build_parser()
