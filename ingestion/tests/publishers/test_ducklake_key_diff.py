from __future__ import annotations

import logging

import duckdb
import pyarrow as pa
import pytest

from ingest.publishers.ducklake import _log_key_column_diffs, _temporary_arrow_view


@pytest.fixture
def real_con():
    con = duckdb.connect(":memory:")
    yield con
    con.close()


@pytest.mark.real_duckdb
def test_all_columns_are_key_columns_early_return(real_con, caplog):
    caplog.set_level(logging.WARNING, logger="ingest.publishers")
    src = pa.table({"id": [1]})
    # quoted_target is irrelevant since function returns before querying
    with _temporary_arrow_view(real_con, src) as view:
        _log_key_column_diffs(
            real_con,
            src,
            quoted_target='"nonexistent"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )
    assert len(caplog.records) == 0


@pytest.mark.real_duckdb
def test_query_error_is_caught(real_con, caplog):
    caplog.set_level(logging.WARNING, logger="ingest.publishers")
    src = pa.table({"id": [1], "val": [10]})
    with _temporary_arrow_view(real_con, src) as view:
        _log_key_column_diffs(
            real_con,
            src,
            quoted_target='"nonexistent"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "WARNING"
    assert "Could not query target" in caplog.text
    assert caplog.records[0].exc_info is not None
