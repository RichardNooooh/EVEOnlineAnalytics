from __future__ import annotations

import logging

import duckdb
import pyarrow as pa
import pytest

from ingest.publishers.ducklake import (
    _log_key_column_diffs,
    _temporary_arrow_view,
)


@pytest.fixture
def real_con():
    con = duckdb.connect(":memory:")
    yield con
    con.close()


@pytest.mark.real_duckdb
def test_matching_keys_same_values_no_warnings(real_con, caplog):
    caplog.set_level(logging.WARNING, logger="ingest.publishers")
    real_con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, 10)) AS t(id, val)")
    src = pa.table({"id": [1], "val": [10]})
    with _temporary_arrow_view(real_con, src) as view:
        _log_key_column_diffs(
            real_con,
            src,
            quoted_target='"t"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )
    assert len(caplog.records) == 0


@pytest.mark.real_duckdb
def test_matching_keys_different_values_logs_warning(real_con, caplog):
    caplog.set_level(logging.WARNING, logger="ingest.publishers")
    real_con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, 10)) AS t(id, val)")
    src = pa.table({"id": [1], "val": [99]})
    with _temporary_arrow_view(real_con, src) as view:
        _log_key_column_diffs(
            real_con,
            src,
            quoted_target='"t"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "WARNING"
    assert "Matched key" in caplog.text
    assert "{'id': 1}" in caplog.text


@pytest.mark.real_duckdb
def test_no_matching_keys_no_warnings(real_con, caplog):
    caplog.set_level(logging.WARNING, logger="ingest.publishers")
    real_con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, 10)) AS t(id, val)")
    src = pa.table({"id": [2], "val": [99]})
    with _temporary_arrow_view(real_con, src) as view:
        _log_key_column_diffs(
            real_con,
            src,
            quoted_target='"t"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )
    assert len(caplog.records) == 0


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


@pytest.mark.real_duckdb
def test_null_value_detected(real_con, caplog):
    caplog.set_level(logging.WARNING, logger="ingest.publishers")

    # Source has NULL, target has value
    real_con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, 10)) AS t(id, val)")
    src = pa.table({"id": [1], "val": pa.array([None], type=pa.int64())})
    with _temporary_arrow_view(real_con, src) as view:
        _log_key_column_diffs(
            real_con,
            src,
            quoted_target='"t"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )
    assert len(caplog.records) == 1
    assert "Matched key" in caplog.text
    assert "{'id': 1}" in caplog.text

    # Reverse: target has NULL, source has value
    caplog.clear()
    real_con.execute("DROP TABLE t")
    real_con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, NULL::INTEGER)) AS t(id, val)")
    src2 = pa.table({"id": [1], "val": [10]})
    with _temporary_arrow_view(real_con, src2) as view2:
        _log_key_column_diffs(
            real_con,
            src2,
            quoted_target='"t"',
            quoted_source=f'"{view2}"',
            key_columns=["id"],
        )
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "WARNING"
    assert "Matched key" in caplog.text


@pytest.mark.real_duckdb
def test_composite_keys_detected(real_con, caplog):
    caplog.set_level(logging.WARNING, logger="ingest.publishers")
    real_con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, 'a', 10)) AS t(id, region, val)")
    src = pa.table({"id": [1], "region": ["a"], "val": [99]})
    with _temporary_arrow_view(real_con, src) as view:
        _log_key_column_diffs(
            real_con,
            src,
            quoted_target='"t"',
            quoted_source=f'"{view}"',
            key_columns=["id", "region"],
        )
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "WARNING"
    assert "{'id': 1, 'region': 'a'}" in caplog.text


@pytest.mark.real_duckdb
def test_multiple_differing_rows(real_con, caplog):
    caplog.set_level(logging.WARNING, logger="ingest.publishers")
    real_con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, 10), (2, 20)) AS t(id, val)")
    src = pa.table({"id": [1, 2], "val": [99, 88]})
    with _temporary_arrow_view(real_con, src) as view:
        _log_key_column_diffs(
            real_con,
            src,
            quoted_target='"t"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )
    assert len(caplog.records) == 2
    for record in caplog.records:
        assert "Matched key" in record.message
