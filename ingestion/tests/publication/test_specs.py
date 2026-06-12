"""Tests for publication specs module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriterMode,
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
)
from eve_ingest.publication.specs import (
    AppendSnapshotRows,
    DatasetPublisherSpec,
    InsertMissingKeysAuthoritativePartition,
    ReplaceReferenceTables,
    SourceDateScope,
    StaticScope,
    WritePolicy,
)
from eve_ingest.raw_objects.primitives import UpdateMode


class DataFactory:
    @staticmethod
    def identity_key(*, source_date: str | None = "2025-01-15") -> dict:
        key: dict[str, str | int | float | bool | None] = {
            "source_system": "everef",
            "endpoint": "market-history",
        }
        if source_date is not None:
            key["source_date"] = source_date
        return key

    @staticmethod
    def dataset_publisher_spec(
        *,
        write_policy: WritePolicy | None = None,
        data_tables: tuple[RawDuckLakeTable, ...] | None = None,
        provenance_tables: tuple[RawDuckLakeProvenanceTable, ...] | None = None,
    ) -> DatasetPublisherSpec:
        return DatasetPublisherSpec(
            dataset_name="market_history",
            update_mode=UpdateMode.MUTABLE,
            data_tables=data_tables if data_tables is not None else (RawDuckLakeTable.MARKET_HISTORY,),
            provenance_tables=provenance_tables or (RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS,),
            publication_scope=SourceDateScope(publication_dataset_name="market_history"),
            write_policy=write_policy or AppendSnapshotRows(),
        )


##############################


class TestSourceDateScope:
    def test_build_with_valid_identity_key(self) -> None:
        scope = SourceDateScope(publication_dataset_name="market_history")
        identity = DataFactory.identity_key(source_date="2025-01-15")
        assert scope.build(identity) == "raw:market_history:source_date=2025-01-15"

    def test_build_with_missing_source_date_raises(self) -> None:
        scope = SourceDateScope(publication_dataset_name="market_history")
        identity = DataFactory.identity_key(source_date=None)
        with pytest.raises(ValueError, match="Missing source_date"):
            scope.build(identity)

    def test_build_with_empty_source_date_raises(self) -> None:
        scope = SourceDateScope(publication_dataset_name="market_history")
        identity = DataFactory.identity_key(source_date="")
        with pytest.raises(ValueError, match="Missing source_date"):
            scope.build(identity)


##############################


class TestStaticScope:
    def test_build_returns_static_string(self) -> None:
        scope = StaticScope(scope="raw:references:")
        assert scope.build(MagicMock()) == "raw:references:"


##############################


class TestDatasetPublisherSpec:
    def test_scope_for_returns_correct_scope_string(self) -> None:
        spec = DataFactory.dataset_publisher_spec()
        identity = DataFactory.identity_key(source_date="2025-01-15")
        assert spec.scope_for(identity) == "raw:market_history:source_date=2025-01-15"

    @pytest.mark.parametrize(
        ("write_policy", "expected_mode"),
        [
            (AppendSnapshotRows(), DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS),
            (
                InsertMissingKeysAuthoritativePartition(key_columns=("date", "type_id")),
                DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS,
            ),
            (ReplaceReferenceTables(), DuckLakeWriterMode.REPLACE_TABLE),
        ],
    )
    def test_writer_mode(self, write_policy: WritePolicy, expected_mode: DuckLakeWriterMode) -> None:
        spec = DataFactory.dataset_publisher_spec(write_policy=write_policy)
        assert spec.writer_mode == expected_mode

    def test_writer_mode_unknown_policy_raises(self) -> None:
        class UnknownPolicy(WritePolicy):
            pass

        spec = DataFactory.dataset_publisher_spec(write_policy=UnknownPolicy())
        with pytest.raises(ValueError, match="Unknown write policy"):
            _ = spec.writer_mode

    @pytest.mark.parametrize(
        ("data_tables", "expected"),
        [
            ((), None),
            ((RawDuckLakeTable.MARKET_HISTORY,), "raw_market_history"),
            (
                (RawDuckLakeTable.MARKET_HISTORY, RawDuckLakeTable.MARKET_ORDERS),
                "raw_market_history,raw_market_orders",
            ),
        ],
    )
    def test_lock_context_table(
        self,
        data_tables: tuple[RawDuckLakeTable, ...],
        expected: str | None,
    ) -> None:
        spec = DataFactory.dataset_publisher_spec(data_tables=data_tables)
        assert spec.lock_context_table() == expected


##############################
