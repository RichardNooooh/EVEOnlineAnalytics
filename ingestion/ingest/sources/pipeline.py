from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from ingest.cache import Cache, CacheObject, CacheResult, GetMode, UpdateMode
from ingest.cli.config import DuckLakeCliConfig, RawFilesCliConfig
from ingest.publishers.ducklake import (
    DuckLakeWriter,
    build_ducklake_attach_config_from_url,
)

logger = logging.getLogger(__name__)


class _PipelineConfig(Protocol):
    """Minimum config surface needed by run_pipeline.

    Satisfied structurally by EverefCliConfig and EverefReferencesCliConfig.
    """

    data_root: str
    raw_files: RawFilesCliConfig
    ducklake: DuckLakeCliConfig


def run_pipeline(
    *,
    dataset_name: str,
    update_mode: UpdateMode,
    objects: list[CacheObject],
    config: _PipelineConfig,
    process_one: Callable[[CacheResult, DuckLakeWriter], bool],
) -> int:
    attach_config = build_ducklake_attach_config_from_url(
        config.ducklake.ducklake_catalog,
        data_path=f"{config.data_root}/datasets/ducklake/raw",
        metadata_schema=config.ducklake.ducklake_metadata_schema,
    )

    total = len(objects)
    success = 0
    failed = 0

    logger.info(
        "Starting pipeline dataset=%s data_root=%s metadata_schema=%s",
        dataset_name,
        config.data_root,
        config.ducklake.ducklake_metadata_schema,
    )

    with Cache(
        dataset_name=dataset_name,
        update_mode=update_mode,
        raw_root=f"{config.data_root}/raw",
        ledger_url=config.raw_files.raw_ledger_url,
    ) as cache:
        results = cache.get_many(objects, mode=GetMode.UNPUBLISHED)

        if not results:
            logger.info("No unpublished raw objects to process dataset=%s", dataset_name)
            return 0

        successful_results: list[CacheResult] = []
        with DuckLakeWriter(attach_config) as writer:
            for result in results:
                if process_one(result, writer):
                    success += 1
                    successful_results.append(result)
                else:
                    failed += 1

        if successful_results:
            cache.pubtrack.mark_published_many(successful_results)

        if success and failed:
            logger.warning(
                "Partial publication dataset=%s success=%d failed=%d total=%d",
                dataset_name,
                success,
                failed,
                total,
            )

    logger.info(
        "Processed %d/%d (%d failed, %d marked_published)",
        success,
        total,
        failed,
        len(successful_results),
    )
    return 1 if failed else 0
