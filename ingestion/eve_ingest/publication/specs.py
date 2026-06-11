from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from eve_ingest.ducklake.locks import ducklake_lock_domains_for_tables
from eve_ingest.ducklake.raw_tables import (
    DuckLakeWriterMode,
    RawDuckLakeProvenanceTable,
    RawDuckLakeTable,
)

if TYPE_CHECKING:
    from eve_ingest.raw_objects.primitives import IdentityKey, UpdateMode

##############################
# Publication Scope
##############################


class PublicationScope(Protocol):
    def build(self, identity_key: IdentityKey) -> str: ...


@dataclass(frozen=True)
class SourceDateScope:
    publication_dataset_name: str

    def build(self, identity_key: IdentityKey) -> str:
        source_date = identity_key.get("source_date")
        if not isinstance(source_date, str) or not source_date:
            raise ValueError(f"Missing source_date for publication scope dataset={self.publication_dataset_name}")
        return f"raw:{self.publication_dataset_name}:source_date={source_date}"


@dataclass(frozen=True)
class StaticScope:
    scope: str

    def build(self, identity_key: IdentityKey) -> str:
        return self.scope


##############################
# Write Policies
##############################


class WritePolicy:
    """Marker base class for dataset write policies."""


@dataclass(frozen=True)
class AppendSnapshotRows(WritePolicy):
    immutable_source_object: bool = True


@dataclass(frozen=True)
class InsertMissingKeysAuthoritativePartition(WritePolicy):
    key_columns: tuple[str, ...]


@dataclass(frozen=True)
class ReplaceReferenceTables(WritePolicy):
    pass


##############################
# Dataset Publisher Spec
##############################


@dataclass(frozen=True)
class DatasetPublisherSpec:
    dataset_name: str
    update_mode: UpdateMode
    data_tables: tuple[RawDuckLakeTable, ...]
    provenance_tables: tuple[RawDuckLakeProvenanceTable, ...]
    publication_scope: PublicationScope
    write_policy: WritePolicy

    def scope_for(self, identity_key: IdentityKey) -> str:
        return self.publication_scope.build(identity_key)

    def lock_context_table(self) -> str | None:
        if not self.data_tables:
            return None
        if len(self.data_tables) == 1:
            return self.data_tables[0].value
        return ",".join(table.value for table in self.data_tables)

    def lock_domains(self) -> tuple[str, ...]:
        """DuckLake advisory lock domains for this dataset's publication scope.

        These lock domains protect only DuckLake raw table and provenance table
        mutations. They do NOT protect:

          - Raw-object ledger publication markers (PostgreSQL).
          - Raw filesystem file writes (downloaded archives).

        See locks.py module docstring for the full lock model scope discussion.
        """
        return ducklake_lock_domains_for_tables(
            data_tables=self.data_tables,
            provenance_tables=self.provenance_tables,
        )

    @property
    def writer_mode(self) -> DuckLakeWriterMode:
        if isinstance(self.write_policy, AppendSnapshotRows):
            return DuckLakeWriterMode.APPEND_SNAPSHOT_ROWS
        if isinstance(self.write_policy, InsertMissingKeysAuthoritativePartition):
            return DuckLakeWriterMode.ASSERT_PARTITION_COVERAGE_INSERT_MISSING_KEYS
        if isinstance(self.write_policy, ReplaceReferenceTables):
            return DuckLakeWriterMode.REPLACE_TABLE
        raise ValueError(f"Unknown write policy: {type(self.write_policy).__name__}")
