from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import duckdb
import pyarrow as pa

from eve_ingest.ducklake.attach_config import DEFAULT_RAW_SCHEMA, DuckLakeAttachConfig
from eve_ingest.ducklake.locks import DuckLakeLockToken
from eve_ingest.ducklake.sql import (
    SqlSource,
    arrow_view,
    quote_identifier,
    quote_sql_string,
)

logger = logging.getLogger("eve_ingest.ducklake")


class DuckLakeSession:
    def __init__(
        self,
        config: DuckLakeAttachConfig,
        *,
        lock_token: DuckLakeLockToken | None = None,
    ) -> None:
        self._config = config
        self._lock_token = lock_token
        self._con: duckdb.DuckDBPyConnection | None = None
        self._transaction_depth = 0
        self._transaction_rollback_only = False

    def __enter__(self) -> DuckLakeSession:
        self._con = duckdb.connect()
        self._attach()
        logger.info(
            "DuckLake session attached alias=%s metadata_schema=%s data_path=%s raw_schema=%s",
            self._config.alias,
            self._config.metadata_schema,
            self._config.data_path,
            DEFAULT_RAW_SCHEMA,
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._con is None:
            return
        self._con.close()
        self._con = None

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            raise RuntimeError("DuckLakeSession is not open; use as context manager")
        return self._con

    @property
    def lock_token(self) -> DuckLakeLockToken | None:
        return self._lock_token

    @property
    def alias(self) -> str:
        return self._config.alias

    def _attach(self) -> None:
        con = self._con
        if con is None:
            raise RuntimeError("DuckLakeSession is not open")
        config = self._config

        if config.attach_uri.startswith("ducklake:postgres:"):
            con.execute("INSTALL postgres")
            con.execute("LOAD postgres")
            self._configure_postgres_pool()

        con.execute("INSTALL ducklake")
        con.execute("LOAD ducklake")
        con.execute(
            f"""
            ATTACH {quote_sql_string(config.attach_uri)} AS {quote_identifier(config.alias)} (
                DATA_PATH {quote_sql_string(config.data_path)},
                METADATA_SCHEMA {quote_sql_string(config.metadata_schema)},
                OVERRIDE_DATA_PATH {"TRUE" if config.override_data_path else "FALSE"}
            )
            """
        )

    def _configure_postgres_pool(self) -> None:
        con = self._con
        if con is None:
            return
        config = self._config
        if config.postgres_pool_max_connections is not None:
            con.execute(f"SET pg_pool_max_connections = {int(config.postgres_pool_max_connections)}")
        if config.postgres_pool_wait_timeout_millis is not None:
            con.execute(f"SET pg_pool_wait_timeout_millis = {int(config.postgres_pool_wait_timeout_millis)}")
        if config.postgres_pool_acquire_mode is not None:
            con.execute(f"SET pg_pool_acquire_mode = {quote_sql_string(config.postgres_pool_acquire_mode)}")

    def quote_sql_string(self, value: str) -> str:
        return quote_sql_string(value)

    def quote_identifier(self, identifier: str) -> str:
        return quote_identifier(identifier)

    @contextmanager
    def prepare_arrow_source(self, arrow_table: pa.Table) -> Iterator[str]:
        with arrow_view(self.connection, arrow_table) as source_name:
            yield source_name

    @contextmanager
    def prepare_sql_source(self, sql_source: SqlSource) -> Iterator[str]:
        con = self.connection
        source_name = f"_sql_source_{uuid4().hex}"
        con.execute(f"CREATE OR REPLACE TEMP VIEW {quote_identifier(source_name)} AS {sql_source.sql}")
        try:
            yield source_name
        finally:
            con.execute(f"DROP VIEW IF EXISTS {quote_identifier(source_name)}")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        con = self.connection

        outermost = self._transaction_depth == 0
        if outermost:
            con.execute("BEGIN")
        self._transaction_depth += 1
        try:
            yield
        except Exception:
            self._transaction_rollback_only = True
            self._transaction_depth -= 1
            if outermost:
                self._transaction_depth = 0
                self._transaction_rollback_only = False
                con.execute("ROLLBACK")
            raise
        else:
            self._transaction_depth -= 1
            if outermost:
                if self._transaction_rollback_only:
                    self._transaction_rollback_only = False
                    con.execute("ROLLBACK")
                    raise RuntimeError("DuckLake transaction marked rollback-only by nested failure")
                try:
                    con.execute("COMMIT")
                except Exception:
                    try:
                        con.execute("ROLLBACK")
                    except Exception:
                        logger.exception("Failed to rollback after DuckLake commit failure")
                    raise
