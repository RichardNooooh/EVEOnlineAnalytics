from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ingest.cache import CacheObject, CacheResult, UpdateMode
from ingest.cli.config import EverefReferencesCliConfig
from ingest.publishers.ducklake import DuckLakeWriteMetrics, DuckLakeWriterMode, RawDuckLakeTable
from ingest.sources.pipeline import PipelineProcessResult, run_pipeline
from tests.sources.everef.conftest import make_cache_result, make_everef_pipeline_config


class _FakeCache:
    def __init__(self, *args, **kwargs) -> None:
        self.pubtrack = type("Pubtrack", (), {"mark_published_many": lambda self, results: None})()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get_many(self, objects: list[CacheObject], mode) -> list[CacheResult]:
        return [
            make_cache_result(
                "/tmp/a.csv.bz2",
                dataset_name="market-history",
                identity_key={"source_date": "2026-01-01"},
                source_url=objects[0].source_url,
            )
        ]


class _FakeWriter:
    def __init__(self, config) -> None:
        self.config = config

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_run_pipeline_logs_summary_and_day_summary(
    monkeypatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("ingest.sources.pipeline.Cache", _FakeCache)
    monkeypatch.setattr("ingest.sources.pipeline.DuckLakeWriter", _FakeWriter)
    pipeline_logger = logging.getLogger("ingest.sources.pipeline")

    config = make_everef_pipeline_config(
        EverefReferencesCliConfig,
        tmp_path,
    )
    objects = [
        CacheObject(
            source_url="https://data.everef.net/market-history/2026/market-history-2026-01-01.csv.bz2",
            identity_key={"source_date": "2026-01-01"},
        )
    ]

    def process_one(result, writer) -> PipelineProcessResult:
        return PipelineProcessResult(
            success=True,
            source_date="2026-01-01",
            write_metrics=(
                DuckLakeWriteMetrics(
                    table=RawDuckLakeTable.MARKET_HISTORY,
                    mode=DuckLakeWriterMode.INSERT_MISSING_KEYS,
                    attempted_rows=10,
                    inserted_rows=7,
                    matched_rows=3,
                    replaced_rows=0,
                ),
            ),
        )

    pipeline_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="ingest.sources.pipeline"):
            exit_code = run_pipeline(
                dataset_name="market-history",
                update_mode=UpdateMode.MUTABLE,
                objects=objects,
                config=config,
                process_one=process_one,
            )
    finally:
        pipeline_logger.removeHandler(caplog.handler)

    assert exit_code == 0
    assert (
        "Pipeline summary dataset=market-history requested_objects=1 processable_objects=1 success=1 failed=0 marked_published=1 exit_code=0"
        in caplog.text
    )
    assert (
        "Pipeline day summary dataset=market-history source_date=2026-01-01 requested_objects=1 processable_objects=1 success=1 failed=0 attempted_rows=10 inserted_rows=7 matched_rows=3 replaced_rows=0"
        in caplog.text
    )
