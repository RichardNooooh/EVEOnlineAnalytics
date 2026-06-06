from __future__ import annotations

from eve_ingest.ducklake.raw_tables import (
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
    provenance_table_for_data_table,
    source_object_column_definitions,
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


def test_source_object_schema_definition_is_shared() -> None:
    columns = source_object_column_definitions()

    assert columns[0] == "source_object_id VARCHAR NOT NULL"
    assert columns[-1] == "row_count BIGINT"
    assert len(columns) == 16
