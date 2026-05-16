from __future__ import annotations

import pytest

from ingest.cli_config import (
    DateRangeCliConfig,
    EverefMarketHistoryCliConfig,
    RawFilesCliConfig,
    StorageCliConfig,
)
from ingest.pipelines import everef


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

    def fake_acquire(start_date, end_date, *, base_url, config, check_headers):
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
                    "check_headers": check_headers,
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
        EverefMarketHistoryCliConfig(
            date_range=DateRangeCliConfig("2025-01-01", "2025-01-01"),
            storage=StorageCliConfig(
                storage_target="mounted",
                data_root="/mnt/eve-market",
            ),
            base_url="https://example.test/history",
            sync_raw=True,
            raw_files=RawFilesCliConfig(
                raw_root="/tmp/raw",
                raw_ledger_url="postgresql://ledger.test/raw",
                raw_max_copies_per_date="0",
            ),
            check_headers=True,
        )
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
        "check_headers": True,
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
        EverefMarketHistoryCliConfig(
            date_range=DateRangeCliConfig("2025-01-01", "2025-01-01"),
            input_source="raw-cache",
            raw_files=RawFilesCliConfig(
                raw_root=str(tmp_path / "raw"),
                raw_ledger_url="postgresql://ledger.test/raw",
            ),
        )
    )

    assert load_info == "load-info"
    assert [call[0] for call in calls] == ["pipeline", "source", "run"]
    assert calls[1][1]["input_source"] == "raw-cache"
    assert calls[1][1]["raw_root"] == str(tmp_path / "raw")
    assert calls[1][1]["raw_ledger_url"] == "postgresql://ledger.test/raw"
