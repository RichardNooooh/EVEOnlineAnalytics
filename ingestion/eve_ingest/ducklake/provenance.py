from __future__ import annotations

import logging

from eve_ingest.ducklake.locks import DuckLakeLockToken, DuckLakeLockViolationError
from eve_ingest.ducklake.raw_tables import (
    RawDuckLakeProvenanceTable,
    provenance_target_for,
)
from eve_ingest.ducklake.session import DuckLakeSession
from eve_ingest.ducklake.sql import (
    datetime_now_utc,
    quote_identifier,
    table_sql,
)

logger = logging.getLogger("eve_ingest.ducklake")


class SourceObjectProvenanceRepository:
    def __init__(
        self,
        session: DuckLakeSession,
        *,
        lock_token: DuckLakeLockToken | None = None,
    ) -> None:
        self._session = session
        self._lock_token = lock_token

    def _require_provenance_table_lock(self, table: RawDuckLakeProvenanceTable) -> None:
        if self._lock_token is None:
            raise DuckLakeLockViolationError(
                f"SourceObjectProvenanceRepository requires DuckLakeLockToken covering provenance table={table.value}"
            )
        self._lock_token.require_provenance_table(table)

    def record_source_object(self, metadata: dict, *, table: RawDuckLakeProvenanceTable) -> None:
        self._require_provenance_table_lock(table)
        self._merge_source_object(metadata, table=table)

    def mark_parsed(self, source_ref_id: str, *, table: RawDuckLakeProvenanceTable) -> None:
        self._require_provenance_table_lock(table)
        self._update_source_object_status(
            source_ref_id,
            table=table,
            data={"status": "parsed", "parsed_at": datetime_now_utc(), "status_reason": None},
        )

    def mark_ingested(self, source_ref_id: str, *, table: RawDuckLakeProvenanceTable) -> None:
        self._require_provenance_table_lock(table)
        self._update_source_object_status(
            source_ref_id,
            table=table,
            data={
                "status": "ingested",
                "ingested_at": datetime_now_utc(),
                "status_reason": None,
            },
        )

    def mark_failed(
        self,
        source_ref_id: str,
        *,
        table: RawDuckLakeProvenanceTable,
        reason: str,
    ) -> None:
        self._require_provenance_table_lock(table)
        self._update_source_object_status(
            source_ref_id,
            table=table,
            data={"status": "failed", "status_reason": reason},
        )

    def ingested_sha256(
        self,
        source_ref_id: str,
        *,
        table: RawDuckLakeProvenanceTable,
    ) -> str | None:
        self._require_provenance_table_lock(table)
        con = self._session.connection
        quoted_target = table_sql(self._session.alias, provenance_target_for(table))
        row = con.execute(
            f"""
            SELECT sha256
            FROM {quoted_target}
            WHERE source_ref_id = ?
                AND status = 'ingested'
            LIMIT 1
            """,
            [source_ref_id],
        ).fetchone()
        if row is None:
            return None
        return row[0]

    def version_is_ingested(
        self,
        source_ref_id: str,
        *,
        sha256: str,
        table: RawDuckLakeProvenanceTable,
    ) -> bool:
        self._require_provenance_table_lock(table)
        con = self._session.connection
        quoted_target = table_sql(self._session.alias, provenance_target_for(table))
        row = con.execute(
            f"""
            SELECT 1
            FROM {quoted_target}
            WHERE source_ref_id = ?
                AND status = 'ingested'
                AND sha256 = ?
            LIMIT 1
            """,
            [source_ref_id, sha256],
        ).fetchone()
        return row is not None

    def _merge_source_object(self, data: dict, *, table: RawDuckLakeProvenanceTable) -> None:
        con = self._session.connection
        quoted_target = table_sql(self._session.alias, provenance_target_for(table))

        columns = list(data.keys())
        col_list = ", ".join(quote_identifier(c) for c in columns)
        select_list = ", ".join("?" for _ in columns)
        update_set = ", ".join(
            f"{quote_identifier(k)} = source.{quote_identifier(k)}" for k in columns if k != "source_ref_id"
        )
        insert_cols = ", ".join(f"source.{quote_identifier(k)}" for k in columns)
        values = list(data.values())

        con.execute(
            f"""
            MERGE INTO {quoted_target} AS target
            USING (SELECT {select_list}) AS source({col_list})
            ON target.source_ref_id = source.source_ref_id
            WHEN MATCHED THEN UPDATE SET {update_set}
            WHEN NOT MATCHED THEN INSERT ({col_list}) VALUES ({insert_cols})
            """,
            values,
        )

    def _update_source_object_status(
        self,
        source_ref_id: str,
        *,
        table: RawDuckLakeProvenanceTable,
        data: dict,
    ) -> None:
        con = self._session.connection
        quoted_target = table_sql(self._session.alias, provenance_target_for(table))
        exists = con.execute(
            f"SELECT 1 FROM {quoted_target} WHERE source_ref_id = ? LIMIT 1",
            [source_ref_id],
        ).fetchone()
        if exists is None:
            raise RuntimeError(f"Provenance row not found for source_ref_id={source_ref_id} table={table.value}")
        columns = list(data.keys())
        set_list = ", ".join(f"{quote_identifier(column)} = ?" for column in columns)
        con.execute(
            f"""
            UPDATE {quoted_target}
            SET {set_list}
            WHERE source_ref_id = ?
            """,
            [*data.values(), source_ref_id],
        )
