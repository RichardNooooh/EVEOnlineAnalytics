"""Tests for key-diff validation logic used by authoritative partition publication."""

from __future__ import annotations

import duckdb
import pyarrow as pa
import pytest
from eve_ingest.ducklake.raw_publish import (
    assert_matched_key_rows_identical,
    assert_target_rows_missing_from_source,
)
from eve_ingest.ducklake.sql import arrow_view


@pytest.fixture
def real_con():
    con = duckdb.connect(":memory:")
    yield con
    con.close()


@pytest.mark.real_duckdb
def test_all_columns_are_key_columns_early_return(real_con):
    src = pa.table({"id": [1]})
    # quoted_target is irrelevant since function returns before querying
    with arrow_view(real_con, src) as view:
        assert_matched_key_rows_identical(
            real_con,
            src,
            quoted_target='"nonexistent"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )


@pytest.mark.real_duckdb
def test_query_error_raises_value_error(real_con):
    src = pa.table({"id": [1], "val": [10]})
    with (
        arrow_view(real_con, src) as view,
        pytest.raises(ValueError, match="Could not query target for key validation"),
    ):
        assert_matched_key_rows_identical(
            real_con,
            src,
            quoted_target='"nonexistent"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )


@pytest.mark.real_duckdb
def test_matched_key_rows_with_identical_values_succeed(real_con):
    src = pa.table({"id": [1, 2], "val": [10, 20], "name": ["trit", "pyerite"]})

    real_con.execute('CREATE TABLE "target" ("id" INTEGER, "val" INTEGER, "name" VARCHAR)')
    real_con.execute("INSERT INTO target VALUES (1, 10, 'trit'), (2, 20, 'pyerite')")

    with arrow_view(real_con, src) as view:
        assert_matched_key_rows_identical(
            real_con,
            src,
            quoted_target='"target"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )


@pytest.mark.real_duckdb
def test_matched_key_rows_with_differing_values_raise(real_con):
    src = pa.table({"id": [1], "val": [99]})

    real_con.execute('CREATE TABLE "target" ("id" INTEGER, "val" INTEGER)')
    real_con.execute('INSERT INTO "target" VALUES (1, 10)')

    with arrow_view(real_con, src) as view, pytest.raises(ValueError, match="differing values"):
        assert_matched_key_rows_identical(
            real_con,
            src,
            quoted_target='"target"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )


@pytest.mark.real_duckdb
def test_matched_key_rows_support_composite_keys(real_con):
    src = pa.table({"region_id": [10000002], "type_id": [34], "val": [10]})

    real_con.execute('CREATE TABLE "target" ("region_id" INTEGER, "type_id" INTEGER, "val" INTEGER)')
    real_con.execute('INSERT INTO "target" VALUES (10000002, 34, 10)')

    with arrow_view(real_con, src) as view:
        assert_matched_key_rows_identical(
            real_con,
            src,
            quoted_target='"target"',
            quoted_source=f'"{view}"',
            key_columns=["region_id", "type_id"],
        )


@pytest.mark.real_duckdb
def test_matched_key_rows_composite_key_differences_raise(real_con):
    src = pa.table({"region_id": [10000002], "type_id": [34], "val": [99]})

    real_con.execute('CREATE TABLE "target" ("region_id" INTEGER, "type_id" INTEGER, "val" INTEGER)')
    real_con.execute('INSERT INTO "target" VALUES (10000002, 34, 10)')

    with arrow_view(real_con, src) as view, pytest.raises(ValueError, match="region_id=10000002, type_id=34"):
        assert_matched_key_rows_identical(
            real_con,
            src,
            quoted_target='"target"',
            quoted_source=f'"{view}"',
            key_columns=["region_id", "type_id"],
        )


@pytest.mark.real_duckdb
def test_matched_key_rows_compare_null_values_with_distinct_semantics(real_con):
    src = pa.table({"id": [1, 2], "val": pa.array([None, 20], type=pa.int64())})

    real_con.execute('CREATE TABLE "target" ("id" INTEGER, "val" INTEGER)')
    real_con.execute('INSERT INTO "target" VALUES (1, NULL), (2, NULL)')

    with arrow_view(real_con, src) as view, pytest.raises(ValueError, match="id=2"):
        assert_matched_key_rows_identical(
            real_con,
            src,
            quoted_target='"target"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )


@pytest.mark.real_duckdb
def test_matched_key_rows_ignore_underscore_prefixed_columns(real_con):
    src = pa.table({"id": [1], "val": [10], "_loaded_at": ["source-ts"]})

    real_con.execute('CREATE TABLE "target" ("id" INTEGER, "val" INTEGER, "_loaded_at" VARCHAR)')
    real_con.execute("INSERT INTO target VALUES (1, 10, 'target-ts')")

    with arrow_view(real_con, src) as view:
        assert_matched_key_rows_identical(
            real_con,
            src,
            quoted_target='"target"',
            quoted_source=f'"{view}"',
            key_columns=["id"],
        )


@pytest.mark.real_duckdb
def test_target_rows_missing_from_source_allows_covered_target_rows(real_con):
    src = pa.table({"source_market_date": ["2026-01-01"], "type_id": [34], "val": [10]})

    real_con.execute('CREATE TABLE "target" ("source_market_date" VARCHAR, "type_id" INTEGER, "val" INTEGER)')
    real_con.execute("INSERT INTO target VALUES ('2026-01-01', 34, 10), ('2026-01-02', 35, 20)")

    with arrow_view(real_con, src) as view:
        assert_target_rows_missing_from_source(
            real_con,
            src,
            quoted_target='"target"',
            quoted_source=f'"{view}"',
            key_columns=["type_id"],
        )


@pytest.mark.real_duckdb
def test_target_rows_missing_from_source_raises_for_missing_target_row(real_con):
    src = pa.table({"source_market_date": ["2026-01-01"], "type_id": [34], "val": [10]})

    real_con.execute('CREATE TABLE "target" ("source_market_date" VARCHAR, "type_id" INTEGER, "val" INTEGER)')
    real_con.execute("INSERT INTO target VALUES ('2026-01-01', 34, 10), ('2026-01-01', 35, 20)")

    with (
        arrow_view(real_con, src) as view,
        pytest.raises(ValueError, match="source_date='2026-01-01', keys=\\{'type_id': 35\\}"),
    ):
        assert_target_rows_missing_from_source(
            real_con,
            src,
            quoted_target='"target"',
            quoted_source=f'"{view}"',
            key_columns=["type_id"],
        )


@pytest.mark.real_duckdb
def test_target_rows_missing_from_source_without_source_market_date_is_noop(real_con):
    src = pa.table({"type_id": [34], "val": [10]})

    with arrow_view(real_con, src) as view:
        assert_target_rows_missing_from_source(
            real_con,
            src,
            quoted_target='"nonexistent"',
            quoted_source=f'"{view}"',
            key_columns=["type_id"],
        )
