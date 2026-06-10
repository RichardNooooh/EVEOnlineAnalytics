from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from eve_ingest.ducklake.attach_config import DEFAULT_RAW_SCHEMA

############################
# Data Classes
############################


@dataclass(frozen=True)
class DuckLakeTableTarget:
    """Logical schema and table name inside attached DuckLake alias."""

    schema: str
    table: str


@dataclass(frozen=True)
class DuckLakeWriteMetrics:
    table: RawDuckLakeTable
    mode: DuckLakeWriterMode
    attempted_rows: int
    inserted_rows: int
    matched_rows: int
    replaced_rows: int


############################
# Enums
############################


class RawDuckLakeTable(StrEnum):
    MARKET_HISTORY = "raw_market_history"
    MARKET_ORDERS = "raw_market_orders"
    FUZZWORK_ORDERS = "raw_fuzzwork_orders"
    REFERENCE_CATEGORIES = "raw_reference_categories"
    REFERENCE_GROUPS = "raw_reference_groups"
    REFERENCE_MARKET_GROUPS = "raw_reference_market_groups"
    REFERENCE_REGIONS = "raw_reference_regions"
    REFERENCE_TYPES = "raw_reference_types"


class DuckLakeWriterMode(StrEnum):
    APPEND_SNAPSHOT_ROWS = "append_snapshot_rows"
    ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS = "assert_partition_coverage_insert_missing_keys"
    REPLACE_TABLE = "replace_table"


class RawDuckLakeProvenanceTable(StrEnum):
    MARKET_HISTORY_OBJECTS = "raw_market_history_objects"
    MARKET_ORDERS_OBJECTS = "raw_market_orders_objects"
    FUZZWORK_ORDERS_OBJECTS = "raw_fuzzwork_orders_objects"
    REFERENCE_OBJECTS = "raw_reference_objects"


############################
# Table Definitions
############################


_SOURCE_REF_COLUMN_DEFINITIONS: Final[tuple[str, ...]] = (
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

_RAW_TABLE_COLUMN_DEFINITIONS: Final[dict[RawDuckLakeTable, tuple[str, ...]]] = {
    RawDuckLakeTable.MARKET_HISTORY: (
        "average DOUBLE",
        "date DATE",
        "highest DOUBLE",
        "lowest DOUBLE",
        "order_count BIGINT",
        "volume BIGINT",
        "http_last_modified TIMESTAMP",
        "region_id BIGINT",
        "type_id BIGINT",
        "source_ref_id VARCHAR",
        "source_market_date DATE",
    ),
    RawDuckLakeTable.MARKET_ORDERS: (
        "order_id BIGINT",
        "type_id BIGINT",
        "region_id BIGINT",
        "location_id BIGINT",
        "system_id BIGINT",
        "range VARCHAR",
        "price DOUBLE",
        "volume_remain BIGINT",
        "volume_total BIGINT",
        "min_volume BIGINT",
        "issued TIMESTAMP",
        "expires TIMESTAMP",
        "duration BIGINT",
        "is_buy_order BOOLEAN",
        "reported_by BIGINT",
        "http_last_modified TIMESTAMP",
        "station_id BIGINT",
        "constellation_id BIGINT",
        "source_ref_id VARCHAR",
        "source_market_date DATE",
        "snapshot_ts TIMESTAMP WITH TIME ZONE",
    ),
    RawDuckLakeTable.FUZZWORK_ORDERS: (
        "order_id BIGINT",
        "type_id BIGINT",
        "issued TIMESTAMP",
        "is_buy_order BOOLEAN",
        "volume_remain BIGINT",
        "volume_total BIGINT",
        "min_volume BIGINT",
        "price DOUBLE",
        "location_id BIGINT",
        "range VARCHAR",
        "duration BIGINT",
        "region_id BIGINT",
        "order_set_id BIGINT",
        "source_ref_id VARCHAR",
        "source_market_date DATE",
        "snapshot_ts TIMESTAMP WITH TIME ZONE",
    ),
    RawDuckLakeTable.REFERENCE_TYPES: (
        "type_id BIGINT",
        "name_en VARCHAR",
        "description_en VARCHAR",
        "group_id BIGINT",
        "category_id BIGINT",
        "market_group_id BIGINT",
        "published BOOLEAN",
        "volume DOUBLE",
        "icon_id BIGINT",
        "meta_group_id BIGINT",
    ),
    RawDuckLakeTable.REFERENCE_REGIONS: (
        "region_id BIGINT",
        "name_en VARCHAR",
        "description_en VARCHAR",
        "universe_id VARCHAR",
        "faction_id BIGINT",
        "wormhole_class_id BIGINT",
    ),
    RawDuckLakeTable.REFERENCE_GROUPS: (
        "group_id BIGINT",
        "name_en VARCHAR",
        "category_id BIGINT",
        "published BOOLEAN",
        "icon_id BIGINT",
    ),
    RawDuckLakeTable.REFERENCE_CATEGORIES: (
        "category_id BIGINT",
        "name_en VARCHAR",
        "published BOOLEAN",
        "icon_id BIGINT",
    ),
    RawDuckLakeTable.REFERENCE_MARKET_GROUPS: (
        "market_group_id BIGINT",
        "name_en VARCHAR",
        "description_en VARCHAR",
        "parent_group_id BIGINT",
        "has_types BOOLEAN",
        "icon_id BIGINT",
    ),
}

_PROVENANCE_TABLES_BY_DATA_TABLE: Final[dict[RawDuckLakeTable, RawDuckLakeProvenanceTable]] = {
    RawDuckLakeTable.MARKET_HISTORY: RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS,
    RawDuckLakeTable.MARKET_ORDERS: RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,
    RawDuckLakeTable.FUZZWORK_ORDERS: RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS,
}


############################
# Helpers
############################


def compute_source_ref_id(source_system: str, endpoint: str, source_url: str) -> str:
    raw = f"{source_system}|{endpoint}|{source_url}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _target_for(table: RawDuckLakeTable) -> DuckLakeTableTarget:
    return DuckLakeTableTarget(schema=DEFAULT_RAW_SCHEMA, table=table.value)


def provenance_target_for(table: RawDuckLakeProvenanceTable) -> DuckLakeTableTarget:
    return DuckLakeTableTarget(schema=DEFAULT_RAW_SCHEMA, table=table.value)


def provenance_table_for_data_table(table: RawDuckLakeTable) -> RawDuckLakeProvenanceTable:
    try:
        return _PROVENANCE_TABLES_BY_DATA_TABLE[table]
    except KeyError as exc:
        raise ValueError(f"No provenance table configured for raw data table: {table.value}") from exc


def source_ref_column_definitions() -> tuple[str, ...]:
    return _SOURCE_REF_COLUMN_DEFINITIONS


def raw_table_column_definitions(table: RawDuckLakeTable) -> tuple[str, ...]:
    return _RAW_TABLE_COLUMN_DEFINITIONS[table]


def raw_table_partition_columns(table: RawDuckLakeTable) -> tuple[str, ...]:
    if table in {RawDuckLakeTable.MARKET_ORDERS, RawDuckLakeTable.FUZZWORK_ORDERS}:
        return ("source_market_date",)
    return ()
