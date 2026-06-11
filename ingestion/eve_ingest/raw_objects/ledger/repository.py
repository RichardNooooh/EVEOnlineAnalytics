"""Ledger runtime for raw object metadata and version tracking.

``RawObjectLedger`` manages a SQLAlchemy engine and bootstraps the schema on
first use.  ``transaction()`` yields a ``LedgerTx`` dataclass with focused
sub-accessors for reading, writing, plan resolution, and publication tracking.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, text

from eve_ingest.raw_objects.ledger.publication_repository import PublicationTrackerTx
from eve_ingest.raw_objects.ledger.reader import RawObjectReader
from eve_ingest.raw_objects.ledger.row_mappers import normalize_ledger_url
from eve_ingest.raw_objects.ledger.schema import _METADATA
from eve_ingest.raw_objects.ledger.writer import RawObjectWriter

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

_BOOTSTRAP_LOCK_DOMAIN = "raw-ledger:bootstrap"


# ── transaction result ─────────────────────────────────────────────────


@dataclass
class LedgerTx:
    reader: RawObjectReader
    writer: RawObjectWriter
    publications: PublicationTrackerTx


# ── ledger engine ──────────────────────────────────────────────────────


class RawObjectLedger:
    """Manages the SQLAlchemy engine and schema for raw object metadata.

    Uses PostgreSQL as the backing store.  The schema is created automatically
    on first transaction unless a pre-existing ledger is supplied.
    """

    def __init__(self, *, ledger_url: str) -> None:
        """Create a new ledger connected to ``ledger_url``.

        Args:
            ledger_url: SQLAlchemy-compatible PostgreSQL URL.  Non-standard
                ``postgres://`` prefixes are normalised to ``postgresql+psycopg``.
        """
        self._engine = create_engine(normalize_ledger_url(ledger_url))
        self._bootstrapped = False

    def __enter__(self) -> RawObjectLedger:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Dispose the SQLAlchemy engine and release connections."""
        self._engine.dispose()

    @contextmanager
    def transaction(self) -> Iterator[LedgerTx]:
        """Yield a ``LedgerTx`` inside an auto-committed transaction.

        Bootstraps the schema on first call.  If the wrapped code raises an
        exception the transaction is rolled back.

        Yields:
            A transaction-bound dataclass with ``reader``, ``writer``,
            ``resolver``, and ``publications`` accessors.
        """
        self._bootstrap()
        with self._engine.begin() as con:
            reader = RawObjectReader(con)
            yield LedgerTx(
                reader=reader,
                writer=RawObjectWriter(con),
                publications=PublicationTrackerTx(con),
            )

    def _bootstrap(self) -> None:
        if self._bootstrapped:
            return
        with self._engine.begin() as con:
            if con.dialect.name == "postgresql":
                con.execute(
                    text("select pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": _bootstrap_lock_key()},
                )
            _METADATA.create_all(con)
        self._bootstrapped = True


def _bootstrap_lock_key() -> int:
    digest = hashlib.blake2b(_BOOTSTRAP_LOCK_DOMAIN.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)
