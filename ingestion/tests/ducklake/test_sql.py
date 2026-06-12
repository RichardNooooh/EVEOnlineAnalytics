"""Tests for SQL utility functions in eve_ingest.ducklake.sql."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

import duckdb
import pyarrow as pa
import pytest
from eve_ingest.ducklake.raw_tables import DuckLakeTableTarget
from eve_ingest.ducklake.sql import (
    arrow_view,
    count_source_rows_with_matches,
    count_source_rows_without_matches,
    datetime_now_utc,
    quote_identifier,
    quote_sql_string,
    table_sql,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def real_con() -> Iterator[duckdb.DuckDBPyConnection]:
    con = duckdb.connect(":memory:")
    yield con
    con.close()


##############################
# QuoteIdentifier Tests
##############################


class TestQuoteIdentifier:
    @pytest.mark.parametrize(
        ("identifier", "expected"),
        [
            ("foo", '"foo"'),
            ("hello_world", '"hello_world"'),
            ("abc123", '"abc123"'),
            ("a", '"a"'),
            ("_private", '"_private"'),
            ("a1_b2", '"a1_b2"'),
            ('with"quote', '"with""quote"'),
        ],
    )
    def test_valid_identifiers(self, identifier: str, expected: str) -> None:
        assert quote_identifier(identifier) == expected

    @pytest.mark.parametrize(
        "identifier",
        [
            "",
        ],
    )
    def test_empty_string_raises(self, identifier: str) -> None:
        with pytest.raises(ValueError, match="SQL identifiers must be non-empty"):
            quote_identifier(identifier)

    @pytest.mark.parametrize(
        "identifier",
        [
            "has space",
            " leading",
            "trailing ",
            "multi word",
        ],
    )
    def test_string_with_spaces_raises(self, identifier: str) -> None:
        with pytest.raises(ValueError, match="SQL identifiers must be non-empty"):
            quote_identifier(identifier)

    @pytest.mark.parametrize(
        "identifier",
        [
            "with-dash",
            "-leading",
            "trailing-",
            "multi-dash-word",
        ],
    )
    def test_string_with_dashes_raises(self, identifier: str) -> None:
        with pytest.raises(ValueError, match="SQL identifiers must be non-empty"):
            quote_identifier(identifier)

    def test_double_quote_escaping(self) -> None:
        assert quote_identifier('has""quote') == '"has""""quote"'

    def test_nested_double_quotes(self) -> None:
        assert quote_identifier('a""b') == '"a""""b"'


##############################
# QuoteSqlString Tests
##############################


class TestQuoteSqlString:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("hello", "'hello'"),
            ("", "''"),
            ("it's", "'it''s'"),
            ("three''quotes", "'three''''quotes'"),
            ("normal text", "'normal text'"),
        ],
    )
    def test_quote_sql_string(self, value: str, expected: str) -> None:
        assert quote_sql_string(value) == expected

    def test_single_quote_escaping(self) -> None:
        assert quote_sql_string("it's") == "'it''s'"
        assert quote_sql_string("'") == "''''"

    def test_empty_string(self) -> None:
        assert quote_sql_string("") == "''"


##############################
# TableSql Tests
##############################


class FakeDuckLakeTableTarget(DuckLakeTableTarget):
    pass


class TestTableSql:
    def test_builds_three_part_name(self) -> None:
        target = FakeDuckLakeTableTarget(schema="raw", table="market_history")
        result = table_sql("dlk", target)
        assert result == '"dlk"."raw"."market_history"'

    def test_with_different_alias(self) -> None:
        target = FakeDuckLakeTableTarget(schema="curated", table="prices")
        result = table_sql("other", target)
        assert result == '"other"."curated"."prices"'

    def test_with_real_ducklake_table_target(self) -> None:
        target = DuckLakeTableTarget(schema="raw", table="raw_market_orders")
        result = table_sql("dlk", target)
        assert result == '"dlk"."raw"."raw_market_orders"'


##############################
# DatetimeNowUtc Tests
##############################


class TestDatetimeNowUtc:
    def test_has_utc_timezone(self) -> None:
        result = datetime_now_utc()
        assert result.tzinfo is not None
        assert result.tzinfo == UTC
        assert str(result.tzinfo) == "UTC"


##############################
# ArrowView Tests
##############################


class TestArrowView:
    @pytest.mark.real_duckdb
    def test_context_manager_creates_and_drops_view(self, real_con: duckdb.DuckDBPyConnection) -> None:
        table = pa.table({"id": [1, 2, 3]})
        with arrow_view(real_con, table) as view_name:
            assert isinstance(view_name, str)
            assert view_name.startswith("_arrow_source_")
            rows = real_con.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()
            assert rows is not None
            assert rows[0] == 3

        # View should be gone after context exit
        with pytest.raises(duckdb.CatalogException):
            real_con.execute(f"SELECT COUNT(*) FROM {view_name}")

    @pytest.mark.real_duckdb
    def test_view_is_queryable_within_context(self, real_con: duckdb.DuckDBPyConnection) -> None:
        table = pa.table({"x": [10, 20, 30], "y": ["a", "b", "c"]})
        with arrow_view(real_con, table) as view_name:
            result = real_con.execute(f"SELECT SUM(x) FROM {view_name}").fetchone()
            assert result is not None
            assert result[0] == 60


##############################
# CountSourceRowsWithMatches Tests
##############################


class TestCountSourceRowsWithMatches:
    @pytest.mark.real_duckdb
    def test_counts_matching_rows(self, real_con: duckdb.DuckDBPyConnection) -> None:
        real_con.execute("CREATE TABLE target (id INTEGER, val INTEGER)")
        real_con.execute("INSERT INTO target VALUES (1, 10), (2, 20), (3, 30)")
        real_con.execute("CREATE TABLE source (id INTEGER)")
        real_con.execute("INSERT INTO source VALUES (1), (2), (3)")

        result = count_source_rows_with_matches(
            real_con,
            quoted_target='"target"',
            quoted_source='"source"',
            key_columns=["id"],
        )
        assert result == 3

    @pytest.mark.real_duckdb
    def test_partial_matches(self, real_con: duckdb.DuckDBPyConnection) -> None:
        real_con.execute("CREATE TABLE target (id INTEGER)")
        real_con.execute("INSERT INTO target VALUES (1), (2)")
        real_con.execute("CREATE TABLE source (id INTEGER)")
        real_con.execute("INSERT INTO source VALUES (1), (2), (3), (4)")

        result = count_source_rows_with_matches(
            real_con,
            quoted_target='"target"',
            quoted_source='"source"',
            key_columns=["id"],
        )
        assert result == 2

    @pytest.mark.real_duckdb
    def test_no_matches(self, real_con: duckdb.DuckDBPyConnection) -> None:
        real_con.execute("CREATE TABLE target (id INTEGER)")
        real_con.execute("INSERT INTO target VALUES (10), (20)")
        real_con.execute("CREATE TABLE source (id INTEGER)")
        real_con.execute("INSERT INTO source VALUES (1), (2)")

        result = count_source_rows_with_matches(
            real_con,
            quoted_target='"target"',
            quoted_source='"source"',
            key_columns=["id"],
        )
        assert result == 0

    @pytest.mark.real_duckdb
    def test_composite_keys(self, real_con: duckdb.DuckDBPyConnection) -> None:
        real_con.execute("CREATE TABLE target (region_id INTEGER, type_id INTEGER)")
        real_con.execute("INSERT INTO target VALUES (10000002, 34), (10000002, 35)")
        real_con.execute("CREATE TABLE source (region_id INTEGER, type_id INTEGER)")
        real_con.execute("INSERT INTO source VALUES (10000002, 34), (10000002, 36)")

        result = count_source_rows_with_matches(
            real_con,
            quoted_target='"target"',
            quoted_source='"source"',
            key_columns=["region_id", "type_id"],
        )
        assert result == 1


##############################
# CountSourceRowsWithoutMatches Tests
##############################


class TestCountSourceRowsWithoutMatches:
    @pytest.mark.real_duckdb
    def test_counts_non_matching_rows(self, real_con: duckdb.DuckDBPyConnection) -> None:
        real_con.execute("CREATE TABLE target (id INTEGER)")
        real_con.execute("INSERT INTO target VALUES (1), (2)")
        real_con.execute("CREATE TABLE source (id INTEGER)")
        real_con.execute("INSERT INTO source VALUES (1), (2), (3), (4)")

        result = count_source_rows_without_matches(
            real_con,
            quoted_target='"target"',
            quoted_source='"source"',
            key_columns=["id"],
        )
        assert result == 2

    @pytest.mark.real_duckdb
    def test_all_match(self, real_con: duckdb.DuckDBPyConnection) -> None:
        real_con.execute("CREATE TABLE target (id INTEGER)")
        real_con.execute("INSERT INTO target VALUES (1), (2), (3)")
        real_con.execute("CREATE TABLE source (id INTEGER)")
        real_con.execute("INSERT INTO source VALUES (1), (2), (3)")

        result = count_source_rows_without_matches(
            real_con,
            quoted_target='"target"',
            quoted_source='"source"',
            key_columns=["id"],
        )
        assert result == 0

    @pytest.mark.real_duckdb
    def test_none_match(self, real_con: duckdb.DuckDBPyConnection) -> None:
        real_con.execute("CREATE TABLE target (id INTEGER)")
        real_con.execute("INSERT INTO target VALUES (10), (20)")
        real_con.execute("CREATE TABLE source (id INTEGER)")
        real_con.execute("INSERT INTO source VALUES (1), (2)")

        result = count_source_rows_without_matches(
            real_con,
            quoted_target='"target"',
            quoted_source='"source"',
            key_columns=["id"],
        )
        assert result == 2

    @pytest.mark.real_duckdb
    def test_composite_key_non_matches(self, real_con: duckdb.DuckDBPyConnection) -> None:
        real_con.execute("CREATE TABLE target (region_id INTEGER, type_id INTEGER)")
        real_con.execute("INSERT INTO target VALUES (10000002, 34)")
        real_con.execute("CREATE TABLE source (region_id INTEGER, type_id INTEGER)")
        real_con.execute("INSERT INTO source VALUES (10000002, 34), (10000002, 35)")

        result = count_source_rows_without_matches(
            real_con,
            quoted_target='"target"',
            quoted_source='"source"',
            key_columns=["region_id", "type_id"],
        )
        assert result == 1
