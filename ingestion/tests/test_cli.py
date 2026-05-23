from __future__ import annotations

import os
import sys
import types
from pathlib import Path

from ingest import (
    DLT_STATE_DIR_ENV,
    activate_dlt_workspace,
    configure_runtime_environment,
    should_activate_dlt_workspace,
)
from ingest.cli import (
    build_everef_market_history_config,
    build_raw_files_sync_config,
    main,
)
from ingest.cli_config import (
    DateRangeCliConfig,
    EverefMarketHistoryCliConfig,
    RawFilesCliConfig,
    StorageCliConfig,
)
from ingest.input_sources import RAW_CACHE_INPUT_SOURCE, URL_INPUT_SOURCE


def test_cli_defaults_to_parquet_loader_format() -> None:
    parser = cli_parser()

    args = parser.parse_args(
        [
            "everef",
            "run-pipeline",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-01",
        ]
    )

    assert args.data_root is None

    config = build_everef_market_history_config(args)

    assert config.loader_file_format == "parquet"
    assert config.destination == "ducklake"
    assert config.storage.storage_target == "local"
    assert config.input_source == RAW_CACHE_INPUT_SOURCE
    assert config.check_headers is False


def test_build_everef_market_history_config_maps_args() -> None:
    parser = cli_parser()

    args = parser.parse_args(
        [
            "everef",
            "run-pipeline",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-02",
            "--base-url",
            "https://example.test/history",
            "--storage-target",
            "mounted",
            "--data-root",
            "/mnt/eve-market",
            "--ducklake-name",
            "arg_lake",
            "--ducklake-catalog",
            "postgresql://arg/catalog",
            "--ducklake-storage",
            "file:///mnt/arg",
            "--input-source",
            URL_INPUT_SOURCE,
            "--sync-raw",
            "--raw-root",
            "/tmp/raw",
            "--raw-max-copies-per-date",
            "9",
            "--check-headers",
        ]
    )

    config = build_everef_market_history_config(args)

    assert config == EverefMarketHistoryCliConfig(
        date_range=DateRangeCliConfig("2025-01-01", "2025-01-02"),
        storage=StorageCliConfig(
            storage_target="mounted",
            data_root="/mnt/eve-market",
        ),
        base_url="https://example.test/history",
        ducklake_name="arg_lake",
        ducklake_catalog="postgresql://arg/catalog",
        ducklake_storage="file:///mnt/arg",
        input_source=URL_INPUT_SOURCE,
        sync_raw=True,
        check_headers=True,
        raw_files=RawFilesCliConfig(
            raw_root="/tmp/raw",
            raw_max_copies_per_date="9",
        ),
    )


def test_build_raw_files_sync_config_maps_args() -> None:
    parser = cli_parser()

    args = parser.parse_args(
        [
            "everef",
            "sync-raw-files",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-02",
            "--storage-target",
            "mounted",
            "--data-root",
            "/mnt/eve-market",
            "--raw-root",
            "/tmp/raw",
            "--raw-ledger-url",
            "postgresql://ledger.test/raw",
            "--raw-max-copies-per-date",
            "0",
            "--check-headers",
        ]
    )

    assert args.command == "everef"
    assert args.everef_command == "sync-raw-files"

    config = build_raw_files_sync_config(args)

    assert config.date_range.start_date == "2025-01-01"
    assert config.date_range.end_date == "2025-01-02"
    assert config.storage.storage_target == "mounted"
    assert config.storage.data_root == "/mnt/eve-market"
    assert config.raw_files.raw_root == "/tmp/raw"
    assert config.raw_files.raw_ledger_url == "postgresql://ledger.test/raw"
    assert config.raw_files.raw_max_copies_per_date == "0"
    assert config.check_headers is True


def test_configure_runtime_environment_defaults_dlt_project_dir(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DLT_PROJECT_DIR", raising=False)
    monkeypatch.delenv(DLT_STATE_DIR_ENV, raising=False)
    monkeypatch.delenv("DLT_DATA_DIR", raising=False)
    monkeypatch.delenv("DLT_LOCAL_DIR", raising=False)

    project_dir = configure_runtime_environment()

    assert os.environ["DLT_PROJECT_DIR"] == str(project_dir)
    assert os.environ["DLT_DATA_DIR"] == str(project_dir / ".dlt" / ".var")
    assert os.environ["DLT_LOCAL_DIR"] == str(project_dir / ".local")


def test_configure_runtime_environment_preserves_override(monkeypatch) -> None:
    monkeypatch.setenv("DLT_PROJECT_DIR", "/tmp/custom-dlt-project")
    monkeypatch.delenv(DLT_STATE_DIR_ENV, raising=False)
    monkeypatch.delenv("DLT_DATA_DIR", raising=False)
    monkeypatch.delenv("DLT_LOCAL_DIR", raising=False)

    project_dir = configure_runtime_environment()

    assert project_dir == Path("/tmp/custom-dlt-project")
    assert os.environ["DLT_PROJECT_DIR"] == "/tmp/custom-dlt-project"
    assert os.environ["DLT_DATA_DIR"] == "/tmp/custom-dlt-project/.dlt/.var"
    assert os.environ["DLT_LOCAL_DIR"] == "/tmp/custom-dlt-project/.local"


def test_configure_runtime_environment_sets_explicit_dlt_scratch(
    monkeypatch, tmp_path
) -> None:
    state_dir = tmp_path / "dlt-state"
    monkeypatch.setenv(DLT_STATE_DIR_ENV, str(state_dir))
    monkeypatch.delenv("DLT_DATA_DIR", raising=False)
    monkeypatch.delenv("DLT_LOCAL_DIR", raising=False)

    project_dir = configure_runtime_environment()

    assert os.environ["DLT_PROJECT_DIR"] == str(project_dir)
    assert os.environ["DLT_DATA_DIR"] == str(state_dir)
    assert os.environ["DLT_LOCAL_DIR"] == str(state_dir / "local")


def test_should_activate_dlt_workspace_skips_explicit_scratch(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(DLT_STATE_DIR_ENV, str(tmp_path / "dlt-state"))

    assert should_activate_dlt_workspace() is False


def test_should_activate_dlt_workspace_skips_direct_dlt_env_override(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv(DLT_STATE_DIR_ENV, raising=False)
    monkeypatch.setenv("DLT_DATA_DIR", str(tmp_path / "dlt-data"))

    assert should_activate_dlt_workspace() is False


def test_should_activate_dlt_workspace_skips_explicit_default_path_override(
    monkeypatch,
) -> None:
    monkeypatch.delenv(DLT_STATE_DIR_ENV, raising=False)
    project_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DLT_DATA_DIR", str(project_dir / ".dlt" / ".var"))

    assert should_activate_dlt_workspace() is False


def test_activate_dlt_workspace_uses_repo_local_state(monkeypatch) -> None:
    monkeypatch.delenv(DLT_STATE_DIR_ENV, raising=False)
    monkeypatch.delenv("DLT_DATA_DIR", raising=False)
    monkeypatch.delenv("DLT_LOCAL_DIR", raising=False)

    project_dir = activate_dlt_workspace()

    from dlt.common.runtime import run_context

    ctx = run_context.active()

    assert type(ctx).__name__ == "WorkspaceRunContext"
    assert Path(ctx.run_dir) == project_dir
    assert Path(ctx.settings_dir) == project_dir / ".dlt"
    assert Path(ctx.data_dir).is_relative_to(project_dir / ".dlt" / ".var")
    assert Path(ctx.local_dir) == project_dir / ".local"


def test_main_activates_workspace_before_importing_pipeline(monkeypatch) -> None:
    call_order: list[str] = []

    def fake_activate() -> Path:
        call_order.append("activate")
        return Path("/tmp/project")

    def fake_run(_config) -> str:
        call_order.append("run")
        return "load-info"

    pipeline_module = types.ModuleType("ingest.pipelines.everef")
    pipeline_module.run_everef_market_history_pipeline = fake_run

    real_import = __import__

    def tracking_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ingest.pipelines.everef":
            call_order.append("import")
            sys.modules[name] = pipeline_module
            return pipeline_module
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("ingest.cli.activate_dlt_workspace", fake_activate)
    monkeypatch.setattr("builtins.__import__", tracking_import)
    monkeypatch.delitem(sys.modules, "ingest.pipelines.everef", raising=False)

    exit_code = main(
        [
            "everef",
            "run-pipeline",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-01-01",
        ]
    )

    assert exit_code == 0
    assert call_order == ["activate", "import", "run"]


def cli_parser():
    from ingest.cli import build_parser

    return build_parser()
