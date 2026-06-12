from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import pytest
from eve_ingest.ducklake.attach_config import DuckLakeAttachConfig
from eve_ingest.ducklake.bootstrap import bootstrap_raw_ducklake
from eve_ingest.ducklake.locks import DuckLakeLockToken, ducklake_lock_domains_for_tables
from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable

if TYPE_CHECKING:
    from collections.abc import Iterator


class KeepConnection:
    """Wraps a real DuckDB connection, ignoring close().

    Lets the connection survive multiple DuckLakeSession with-blocks
    so later blocks see the same in-memory data.
    """

    def __init__(self) -> None:
        self._con = duckdb.connect(":memory:")

    def __getattr__(self, name: str):
        return getattr(self._con, name)

    def close(self) -> None:
        pass


@pytest.fixture
def shared_con(monkeypatch) -> Iterator[duckdb.DuckDBPyConnection]:
    """Real in-memory DuckDB connection that is NOT closed on writer exit."""
    con = KeepConnection()
    monkeypatch.setattr("eve_ingest.ducklake.session.duckdb.connect", lambda: con)
    monkeypatch.setattr("eve_ingest.ducklake.bootstrap.duckdb.connect", lambda: con)
    monkeypatch.setattr(
        "eve_ingest.ducklake.session.DuckLakeSession._attach",
        lambda self: None,
    )
    monkeypatch.setattr(
        "eve_ingest.ducklake.bootstrap._attach_bootstrap",
        lambda c, config: None,
    )
    bootstrap_raw_ducklake(ATTACH)
    yield con._con
    con._con.close()


ATTACH = DuckLakeAttachConfig(
    attach_uri=":memory:",
    data_path="",
    metadata_schema="memory",
    alias="memory",
)


def create_lock_token() -> DuckLakeLockToken:
    return DuckLakeLockToken.unsafe_for_tests(
        ducklake_lock_domains_for_tables(
            data_tables=tuple(RawDuckLakeTable),
            provenance_tables=tuple(RawDuckLakeProvenanceTable),
        )
    )
