from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from eve_ingest.ducklake.attach_config import DEFAULT_RAW_SCHEMA


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


class RawDuckLakeTable(StrEnum):
    RAW_SOURCE_OBJECTS = "raw_source_objects"
    MARKET_HISTORY = "raw_market_history"
    MARKET_ORDERS = "raw_market_orders"
    FUZZWORK_ORDERS = "raw_fuzzwork_orders"
    REFERENCE_CATEGORIES = "raw_reference_categories"
    REFERENCE_GROUPS = "raw_reference_groups"
    REFERENCE_MARKET_GROUPS = "raw_reference_market_groups"
    REFERENCE_REGIONS = "raw_reference_regions"
    REFERENCE_TYPES = "raw_reference_types"


class DuckLakeWriterMode(StrEnum):
    INSERT_MISSING_KEYS = "insert_missing_keys"
    ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS = "assert_partition_coverage_insert_missing_keys"
    REPLACE_TABLE = "replace_table"


def compute_source_object_id(source_system: str, endpoint: str, source_url: str) -> str:
    raw = f"{source_system}|{endpoint}|{source_url}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _target_for(table: RawDuckLakeTable) -> DuckLakeTableTarget:
    return DuckLakeTableTarget(schema=DEFAULT_RAW_SCHEMA, table=table.value)
