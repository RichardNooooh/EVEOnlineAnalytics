from __future__ import annotations

from eve_ingest.cli.config import DuckLakeBootstrapCliConfig
from eve_ingest.ducklake.attach_config import build_ducklake_attach_config_from_url
from eve_ingest.ducklake.locks import hold_ducklake_lock_domains, raw_bootstrap_lock_domains
from eve_ingest.ducklake.writer import bootstrap_raw_ducklake


def run_raw_bootstrap(config: DuckLakeBootstrapCliConfig) -> int:
    attach_config = build_ducklake_attach_config_from_url(
        config.ducklake.ducklake_catalog,
        data_path=f"{config.data_root}/datasets/ducklake/raw",
        metadata_schema=config.ducklake.ducklake_metadata_schema,
        postgres_pool_max_connections=config.ducklake.pg_pool_max_connections,
        postgres_pool_wait_timeout_millis=config.ducklake.pg_pool_wait_timeout_millis,
        postgres_pool_acquire_mode=config.ducklake.pg_pool_acquire_mode,
    )
    with hold_ducklake_lock_domains(
        catalog_url=config.ducklake.ducklake_catalog,
        lock_domains=raw_bootstrap_lock_domains(),
        timeout_seconds=config.ducklake.lock_wait_timeout_seconds,
    ):
        bootstrap_raw_ducklake(attach_config)
    return 0
