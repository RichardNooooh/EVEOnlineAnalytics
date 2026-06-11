"""Module-level DB helpers shared by all ledger sub-accessors.

Isolated in its own module to avoid circular imports between ``reader.py``,
``writer.py``, ``runtime.py``, and ``plans.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, CursorResult, RowMapping
    from sqlalchemy.sql import Executable


def _execute(con: Connection, statement: Executable) -> CursorResult:
    return con.execute(statement)


def _fetchone(con: Connection, statement: Executable) -> RowMapping | None:
    return con.execute(statement).mappings().first()


def _fetchall(con: Connection, statement: Executable) -> list[RowMapping]:
    return list(con.execute(statement).mappings().all())
