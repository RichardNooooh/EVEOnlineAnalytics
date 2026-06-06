from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from eve_ingest.ducklake.locks import ducklake_lock_domains_for_tables
from eve_ingest.ducklake.raw_tables import DuckLakeWriterMode, RawDuckLakeProvenanceTable, RawDuckLakeTable
from eve_ingest.raw_objects.primitives import IdentityKey, UpdateMode


@dataclass(frozen=True)
class PublisherSpec:
    dataset_name: str
    update_mode: UpdateMode
    data_tables: tuple[RawDuckLakeTable, ...]
    provenance_tables: tuple[RawDuckLakeProvenanceTable, ...]
    writer_mode: DuckLakeWriterMode
    publication_scope_builder: Callable[[IdentityKey], str]

    def publication_scope(self, identity_key: IdentityKey) -> str:
        return self.publication_scope_builder(identity_key)

    def lock_domains(self) -> tuple[str, ...]:
        return ducklake_lock_domains_for_tables(
            data_tables=self.data_tables,
            provenance_tables=self.provenance_tables,
        )

    def lock_context_table(self) -> str | None:
        if not self.data_tables:
            return None
        if len(self.data_tables) == 1:
            return self.data_tables[0].value
        return ",".join(table.value for table in self.data_tables)


def source_date_publication_scope(publication_dataset_name: str) -> Callable[[IdentityKey], str]:
    def build_scope(identity_key: IdentityKey) -> str:
        source_date = identity_key.get("source_date")
        if not isinstance(source_date, str) or not source_date:
            raise ValueError(f"Missing source_date for publication scope dataset: {publication_dataset_name}")
        return f"raw:{publication_dataset_name}:source_date={source_date}"

    return build_scope
