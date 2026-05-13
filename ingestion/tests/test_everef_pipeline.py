from __future__ import annotations

import pytest

from ingest.pipelines import everef
from ingest.publishers import ducklake as ducklake_pub
from ingest.storage_config import DATA_ROOT_ENV_VAR


class FakeDuckLakeCredentials:
    def __init__(self, name: str, *, catalog: str, storage: str) -> None:
        self.name = name
        self.catalog = catalog
        self.storage = storage


def fake_ducklake_destination(
    credentials: FakeDuckLakeCredentials,
) -> dict[str, object]:
    return {"credentials": credentials}


def patch_ducklake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ducklake_pub, "DuckLakeCredentials", FakeDuckLakeCredentials)
    monkeypatch.setattr(ducklake_pub, "ducklake", fake_ducklake_destination)


def test_ducklake_destination_uses_local_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_NAME_ENV_VAR, raising=False)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_CATALOG_ENV_VAR, raising=False)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR, raising=False)
    monkeypatch.delenv(DATA_ROOT_ENV_VAR, raising=False)

    destination_config = ducklake_pub.build_destination_config("ducklake")

    credentials = destination_config["credentials"]
    assert credentials.name == ducklake_pub.DEFAULT_DUCKLAKE_NAME
    assert credentials.catalog == ducklake_pub.local_ducklake_catalog()
    assert credentials.storage == ducklake_pub.local_ducklake_storage()
    assert credentials.catalog.startswith("sqlite:///")
    assert credentials.catalog.endswith(
        "/ingestion/.local/ducklake/everef_market_history/lake_catalog.sqlite"
    )
    assert credentials.storage.startswith("file://")
    assert credentials.storage.endswith(
        "/ingestion/.local/ducklake/everef_market_history/files"
    )


def test_ducklake_destination_creates_local_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_CATALOG_ENV_VAR, raising=False)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR, raising=False)
    monkeypatch.setattr(
        ducklake_pub, "local_ducklake_root", lambda: tmp_path / "ducklake"
    )

    destination_config = ducklake_pub.build_destination_config("ducklake")

    assert destination_config["credentials"].catalog.endswith("/lake_catalog.sqlite")
    assert (tmp_path / "ducklake").is_dir()
    assert (tmp_path / "ducklake/files").is_dir()


def test_ducklake_destination_uses_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.setenv(ducklake_pub.DUCKLAKE_NAME_ENV_VAR, "env_lake")
    monkeypatch.setenv(
        ducklake_pub.DUCKLAKE_CATALOG_ENV_VAR, "postgresql://env/catalog"
    )
    monkeypatch.setenv(ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR, "file:///mnt/env")

    destination_config = ducklake_pub.build_destination_config("ducklake")

    credentials = destination_config["credentials"]
    assert credentials.name == "env_lake"
    assert credentials.catalog == "postgresql://env/catalog"
    assert credentials.storage == "file:///mnt/env"


def test_ducklake_destination_explicit_args_override_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.setenv(ducklake_pub.DUCKLAKE_NAME_ENV_VAR, "env_lake")
    monkeypatch.setenv(
        ducklake_pub.DUCKLAKE_CATALOG_ENV_VAR, "postgresql://env/catalog"
    )
    monkeypatch.setenv(ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR, "file:///mnt/env")

    destination_config = ducklake_pub.build_destination_config(
        "ducklake",
        "arg_lake",
        "postgresql://arg/catalog",
        "file:///mnt/arg",
    )

    credentials = destination_config["credentials"]
    assert credentials.name == "arg_lake"
    assert credentials.catalog == "postgresql://arg/catalog"
    assert credentials.storage == "file:///mnt/arg"


def test_ducklake_destination_rejects_mounted_storage_with_default_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_CATALOG_ENV_VAR, raising=False)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR, raising=False)
    monkeypatch.delenv(DATA_ROOT_ENV_VAR, raising=False)

    with pytest.raises(
        ValueError,
        match="mounted DuckLake storage requires a non-local catalog.*PostgreSQL",
    ):
        ducklake_pub.build_destination_config(
            "ducklake",
            storage_target="mounted",
        )


def test_ducklake_destination_uses_mounted_storage_target_with_explicit_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR, raising=False)
    monkeypatch.delenv(DATA_ROOT_ENV_VAR, raising=False)

    destination_config = ducklake_pub.build_destination_config(
        "ducklake",
        ducklake_catalog="postgresql://lake/catalog",
        storage_target="mounted",
    )

    credentials = destination_config["credentials"]
    assert credentials.catalog == "postgresql://lake/catalog"
    assert (
        credentials.storage
        == "file:///opt/eve-market/data/ducklake/everef/market_history"
    )


def test_ducklake_destination_rejects_explicit_mounted_storage_with_default_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_CATALOG_ENV_VAR, raising=False)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR, raising=False)

    with pytest.raises(
        ValueError,
        match="mounted DuckLake storage requires a non-local catalog.*PostgreSQL",
    ):
        ducklake_pub.build_destination_config(
            "ducklake",
            ducklake_storage=ducklake_pub.mounted_ducklake_storage("/mnt/data"),
            data_root="/mnt/data",
        )


def test_ducklake_destination_rejects_env_mounted_storage_with_default_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_CATALOG_ENV_VAR, raising=False)
    monkeypatch.setenv(
        ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR,
        ducklake_pub.mounted_ducklake_storage("/mnt/data"),
    )

    with pytest.raises(
        ValueError,
        match="mounted DuckLake storage requires a non-local catalog.*PostgreSQL",
    ):
        ducklake_pub.build_destination_config("ducklake", data_root="/mnt/data")


@pytest.mark.parametrize("storage_source", ["explicit", "env"])
def test_ducklake_destination_allows_mounted_storage_with_postgres_catalog(
    monkeypatch: pytest.MonkeyPatch,
    storage_source: str,
) -> None:
    patch_ducklake(monkeypatch)
    mounted_storage = ducklake_pub.mounted_ducklake_storage("/mnt/data")
    kwargs = (
        {"ducklake_storage": mounted_storage} if storage_source == "explicit" else {}
    )
    if storage_source == "env":
        monkeypatch.setenv(ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR, mounted_storage)

    destination_config = ducklake_pub.build_destination_config(
        "ducklake",
        ducklake_catalog="postgresql://lake/catalog",
        data_root="/mnt/data",
        **kwargs,
    )

    credentials = destination_config["credentials"]
    assert credentials.catalog == "postgresql://lake/catalog"
    assert credentials.storage == mounted_storage


def test_ducklake_destination_uses_data_root_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR, raising=False)
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, "/mnt/env-root")

    destination_config = ducklake_pub.build_destination_config(
        "ducklake",
        ducklake_catalog="postgresql://lake/catalog",
        storage_target="mounted",
        data_root="/mnt/arg-root",
    )

    credentials = destination_config["credentials"]
    assert credentials.storage == "file:///mnt/arg-root/ducklake/everef/market_history"


def test_ducklake_storage_override_skips_mounted_data_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, "")

    destination_config = ducklake_pub.build_destination_config(
        "ducklake",
        ducklake_catalog="postgresql://lake/catalog",
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
        ducklake_pub.build_destination_config("ducklake", **kwargs)


@pytest.mark.parametrize(
    ("env_var", "message"),
    [
        (ducklake_pub.DUCKLAKE_NAME_ENV_VAR, ducklake_pub.DUCKLAKE_NAME_ENV_VAR),
        (ducklake_pub.DUCKLAKE_CATALOG_ENV_VAR, ducklake_pub.DUCKLAKE_CATALOG_ENV_VAR),
        (ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR, ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR),
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
        ducklake_pub.build_destination_config("ducklake")


def test_ducklake_destination_rejects_empty_env_data_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.delenv(ducklake_pub.DUCKLAKE_STORAGE_ENV_VAR, raising=False)
    monkeypatch.delenv(DATA_ROOT_ENV_VAR, raising=False)
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, "")

    with pytest.raises(ValueError, match=DATA_ROOT_ENV_VAR):
        ducklake_pub.build_destination_config("ducklake", storage_target="mounted")


def test_non_ducklake_destination_returns_raw_string() -> None:
    assert ducklake_pub.build_destination_config("filesystem") == "filesystem"


def test_run_pipeline_sync_raw_acquires_then_loads_from_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    class FakePipeline:
        def run(self, source, *, loader_file_format: str):
            calls.append(("run", (source, loader_file_format)))
            return "load-info"

    def fake_pipeline(**kwargs):
        calls.append(("pipeline", kwargs))
        return FakePipeline()

    def fake_acquire(start_date, end_date, *, base_url, config):
        calls.append(
            (
                "acquire",
                {
                    "start_date": start_date,
                    "end_date": end_date,
                    "base_url": base_url,
                    "raw_root": str(config.raw_root),
                    "ledger_url": config.ledger_url,
                    "max_copies_per_date": config.max_copies_per_date,
                },
            )
        )
        return []

    def fake_source(start_date, end_date, **kwargs):
        calls.append(
            (
                "source",
                {
                    "start_date": start_date,
                    "end_date": end_date,
                    **kwargs,
                },
            )
        )
        return "source"

    monkeypatch.setattr(
        everef, "_build_destination_config", lambda *args, **kwargs: "dest"
    )
    monkeypatch.setattr(everef.dlt, "pipeline", fake_pipeline)
    monkeypatch.setattr(everef, "acquire_everef_market_history_files", fake_acquire)
    monkeypatch.setattr(everef, "everef_market_history_source", fake_source)

    load_info = everef.run_everef_market_history_pipeline(
        "2025-01-01",
        "2025-01-01",
        storage_target="mounted",
        data_root="/mnt/eve-market",
        base_url="https://example.test/history",
        sync_raw=True,
        raw_root="/tmp/raw",
        raw_ledger_url="postgresql://ledger.test/raw",
        raw_max_copies_per_date="0",
    )

    assert load_info == "load-info"
    assert [call[0] for call in calls] == ["pipeline", "acquire", "source", "run"]
    assert calls[1][1] == {
        "start_date": "2025-01-01",
        "end_date": "2025-01-01",
        "base_url": "https://example.test/history",
        "raw_root": "/tmp/raw",
        "ledger_url": "postgresql://ledger.test/raw",
        "max_copies_per_date": 0,
    }
    assert calls[2][1]["input_source"] == "raw-cache"
    assert calls[2][1]["raw_root"] == "/tmp/raw"
    assert calls[2][1]["raw_ledger_url"] == "postgresql://ledger.test/raw"
    assert "storage_target" not in calls[2][1]
    assert "data_root" not in calls[2][1]


def test_run_pipeline_raw_cache_resolves_config_for_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    calls: list[tuple[str, object]] = []

    class FakePipeline:
        def run(self, source, *, loader_file_format: str):
            calls.append(("run", (source, loader_file_format)))
            return "load-info"

    def fake_pipeline(**kwargs):
        calls.append(("pipeline", kwargs))
        return FakePipeline()

    def fake_source(start_date, end_date, **kwargs):
        calls.append(
            (
                "source",
                {
                    "start_date": start_date,
                    "end_date": end_date,
                    **kwargs,
                },
            )
        )
        return "source"

    monkeypatch.setattr(
        everef, "_build_destination_config", lambda *args, **kwargs: "dest"
    )
    monkeypatch.setattr(everef.dlt, "pipeline", fake_pipeline)
    monkeypatch.setattr(everef, "everef_market_history_source", fake_source)

    load_info = everef.run_everef_market_history_pipeline(
        "2025-01-01",
        "2025-01-01",
        input_source="raw-cache",
        raw_root=str(tmp_path / "raw"),
        raw_ledger_url="postgresql://ledger.test/raw",
    )

    assert load_info == "load-info"
    assert [call[0] for call in calls] == ["pipeline", "source", "run"]
    assert calls[1][1]["input_source"] == "raw-cache"
    assert calls[1][1]["raw_root"] == str(tmp_path / "raw")
    assert calls[1][1]["raw_ledger_url"] == "postgresql://ledger.test/raw"


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


def test_cli_accepts_raw_file_sync_command() -> None:
    parser = everef_cli_parser()

    args = parser.parse_args(
        [
            "raw-files",
            "sync-everef-market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-01",
            "--raw-root",
            "/tmp/raw",
            "--raw-ledger-url",
            "postgresql://ledger.test/raw",
            "--raw-max-copies-per-date",
            "0",
        ]
    )

    assert args.command == "raw-files"
    assert args.raw_command == "sync-everef-market-history"
    assert args.raw_root == "/tmp/raw"
    assert args.raw_ledger_url == "postgresql://ledger.test/raw"
    assert args.raw_max_copies_per_date == "0"


def test_cli_accepts_raw_cache_input_options() -> None:
    parser = everef_cli_parser()

    args = parser.parse_args(
        [
            "everef-market-history",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-01",
            "--input-source",
            "raw-cache",
            "--sync-raw",
            "--raw-max-copies-per-date",
            "9",
        ]
    )

    assert args.input_source == "raw-cache"
    assert args.sync_raw is True
    assert args.raw_max_copies_per_date == "9"


def everef_cli_parser():
    from ingest.cli import build_parser

    return build_parser()
