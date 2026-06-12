"""Tests for raw table schema definitions, provenance table mapping, and partitioning."""

from __future__ import annotations

import pytest
from eve_ingest.ducklake.raw_tables import (
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
    provenance_table_for_data_table,
    raw_table_column_definitions,
    raw_table_partition_columns,
    source_ref_column_definitions,
)


def test_provenance_table_selection_matches_dataset_scope() -> None:
    assert (
        provenance_table_for_data_table(RawDuckLakeTable.MARKET_HISTORY)
        is RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS
    )
    assert (
        provenance_table_for_data_table(RawDuckLakeTable.MARKET_ORDERS)
        is RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS
    )
    assert (
        provenance_table_for_data_table(RawDuckLakeTable.FUZZWORK_ORDERS)
        is RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS
    )


@pytest.mark.parametrize(
    "table",
    [
        RawDuckLakeTable.REFERENCE_CATEGORIES,
        RawDuckLakeTable.REFERENCE_GROUPS,
        RawDuckLakeTable.REFERENCE_MARKET_GROUPS,
        RawDuckLakeTable.REFERENCE_REGIONS,
        RawDuckLakeTable.REFERENCE_TYPES,
    ],
)
def test_provenance_table_selection_rejects_reference_tables(table: RawDuckLakeTable) -> None:
    with pytest.raises(ValueError, match=f"No provenance table configured for raw data table: {table.value}"):
        provenance_table_for_data_table(table)


def test_source_object_schema_definition_is_shared() -> None:
    assert source_ref_column_definitions() == (
        "source_ref_id VARCHAR NOT NULL",
        "source_system VARCHAR NOT NULL",
        "endpoint VARCHAR NOT NULL",
        "source_url VARCHAR NOT NULL",
        "storage_uri VARCHAR",
        "source_market_date DATE",
        "snapshot_ts TIMESTAMP",
        "last_modified TIMESTAMP",
        "content_length BIGINT",
        "sha256 VARCHAR",
        "downloaded_at TIMESTAMP",
        "parsed_at TIMESTAMP",
        "ingested_at TIMESTAMP",
        "status VARCHAR NOT NULL",
        "status_reason VARCHAR",
    )


def test_market_orders_schema_matches_everef_snapshot_columns() -> None:
    columns = raw_table_column_definitions(RawDuckLakeTable.MARKET_ORDERS)

    assert "location_id BIGINT" in columns
    assert "station_id BIGINT" in columns
    assert "constellation_id BIGINT" in columns


def test_snapshot_order_tables_partition_by_source_market_date() -> None:
    assert raw_table_partition_columns(RawDuckLakeTable.MARKET_ORDERS) == ("source_market_date",)
    assert raw_table_partition_columns(RawDuckLakeTable.FUZZWORK_ORDERS) == ("source_market_date",)
    assert raw_table_partition_columns(RawDuckLakeTable.MARKET_HISTORY) == ()
