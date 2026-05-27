from __future__ import annotations

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from ingest.cache.ledger.mappers import raw_object_publication_values
from ingest.cache.ledger._db import _execute, _fetchone, _fetchall
from ingest.cache.ledger.schema import raw_object_publications
from ingest.cache.ledger.types import PublicationContext, RawObjectRef


class PublicationTrackerTx:
    def __init__(self, con: Connection) -> None:
        self._con = con

    def mark_published(
        self,
        *,
        ref: RawObjectRef,
        sha256: str,
        version_id: str,
        context: PublicationContext,
    ) -> None:
        statement = pg_insert(raw_object_publications).values(
            **raw_object_publication_values(
                ref=ref,
                sha256=sha256,
                version_id=version_id,
                context=context,
            )
        )
        _execute(
            self._con,
            statement.on_conflict_do_nothing(
                index_elements=[
                    raw_object_publications.c.source_name,
                    raw_object_publications.c.dataset_name,
                    raw_object_publications.c.identity_hash,
                    raw_object_publications.c.sha256,
                ]
            ),
        )

    def mark_published_many(
        self,
        publications: list[tuple[RawObjectRef, str, str, PublicationContext]],
    ) -> None:
        if not publications:
            return
        values = [
            raw_object_publication_values(
                ref=ref,
                sha256=sha256,
                version_id=version_id,
                context=ctx,
            )
            for ref, sha256, version_id, ctx in publications
        ]
        statement = pg_insert(raw_object_publications).values(values)
        _execute(
            self._con,
            statement.on_conflict_do_nothing(
                index_elements=[
                    raw_object_publications.c.source_name,
                    raw_object_publications.c.dataset_name,
                    raw_object_publications.c.identity_hash,
                    raw_object_publications.c.sha256,
                ]
            ),
        )

    def is_published(
        self,
        *,
        ref: RawObjectRef,
        sha256: str,
    ) -> bool:
        row = _fetchone(
            self._con,
            select(raw_object_publications.c.id).where(
                raw_object_publications.c.source_name == ref.source_name,
                raw_object_publications.c.dataset_name == ref.dataset_name,
                raw_object_publications.c.identity_hash == ref.identity_hash,
                raw_object_publications.c.sha256 == sha256,
            ),
        )
        return row is not None

    def filter_published(
        self,
        *,
        group_key: tuple[str, str],
        versions: list[tuple[str, str]],
    ) -> set[tuple[str, str]]:
        if not versions:
            return set()
        source_name, dataset_name = group_key
        rows = _fetchall(
            self._con,
            select(
                raw_object_publications.c.identity_hash,
                raw_object_publications.c.sha256,
            ).where(
                raw_object_publications.c.source_name == source_name,
                raw_object_publications.c.dataset_name == dataset_name,
                tuple_(
                    raw_object_publications.c.identity_hash,
                    raw_object_publications.c.sha256,
                ).in_(versions),
            ),
        )
        return {(row["identity_hash"], row["sha256"]) for row in rows}
