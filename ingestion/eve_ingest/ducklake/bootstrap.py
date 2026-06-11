from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb

from eve_ingest.ducklake.attach_config import DEFAULT_RAW_SCHEMA, DuckLakeAttachConfig, _build_default_attach_config
from eve_ingest.ducklake.locks import hold_ducklake_lock_domains, raw_bootstrap_lock_domains
from eve_ingest.ducklake.raw_publish import add_missing_columns, ensure_expected_partitioning
from eve_ingest.ducklake.raw_tables import (
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
    _target_for,
    provenance_target_for,
    raw_table_column_definitions,
    raw_table_partition_columns,
    source_ref_column_definitions,
)
from eve_ingest.ducklake.sql import quote_identifier, table_sql

if TYPE_CHECKING:
    from eve_ingest.cli.config import DuckLakeBootstrapCliConfig


def bootstrap_raw_ducklake(config: DuckLakeAttachConfig | None = None) -> None:
    attach = config or _build_default_attach_config()
    con = duckdb.connect()
    try:
        _attach_bootstrap(con, attach)
        schema_name = f"{quote_identifier(attach.alias)}.{quote_identifier(DEFAULT_RAW_SCHEMA)}"
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
        for table in RawDuckLakeTable:
            target = _target_for(table)
            quoted_target = table_sql(attach.alias, target)
            table_column_sql = ",\n                    ".join(raw_table_column_definitions(table))
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {quoted_target} (
                    {table_column_sql}
                )
                """
            )
            add_missing_columns(
                con,
                alias=attach.alias,
                target=target,
                column_definitions=raw_table_column_definitions(table),
            )
            partition_columns = raw_table_partition_columns(table)
            if partition_columns:
                ensure_expected_partitioning(
                    con,
                    alias=attach.alias,
                    target=target,
                    partition_columns=partition_columns,
                )
        column_sql = ",\n                ".join(source_ref_column_definitions())
        for table in RawDuckLakeProvenanceTable:
            target = provenance_target_for(table)
            quoted_target = table_sql(attach.alias, target)
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {quoted_target} (
                    {column_sql}
                )
                """
            )
            add_missing_columns(
                con,
                alias=attach.alias,
                target=target,
                column_definitions=source_ref_column_definitions(),
            )
    finally:
        con.close()


def _attach_bootstrap(
    con: duckdb.DuckDBPyConnection,
    config: DuckLakeAttachConfig,
) -> None:
    if config.attach_uri.startswith("ducklake:postgres:"):
        con.execute("INSTALL postgres")
        con.execute("LOAD postgres")
        if config.postgres_pool_max_connections is not None:
            con.execute(f"SET pg_pool_max_connections = {int(config.postgres_pool_max_connections)}")
        if config.postgres_pool_wait_timeout_millis is not None:
            con.execute(f"SET pg_pool_wait_timeout_millis = {int(config.postgres_pool_wait_timeout_millis)}")
        if config.postgres_pool_acquire_mode is not None:
            con.execute(f"SET pg_pool_acquire_mode = '{config.postgres_pool_acquire_mode}'")
    con.execute("INSTALL ducklake")
    con.execute("LOAD ducklake")
    con.execute(
        f"""
        ATTACH '{config.attach_uri}' AS {quote_identifier(config.alias)} (
            DATA_PATH '{config.data_path}',
            METADATA_SCHEMA '{config.metadata_schema}',
            OVERRIDE_DATA_PATH {"TRUE" if config.override_data_path else "FALSE"}
        )
        """
    )


def run_raw_bootstrap(config: DuckLakeBootstrapCliConfig) -> int:
    from eve_ingest.ducklake.attach_config import build_ducklake_attach_config_from_url

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
