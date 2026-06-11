from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import psycopg
from sqlalchemy.engine import make_url

from eve_ingest.ducklake.raw_tables import RawDuckLakeProvenanceTable, RawDuckLakeTable

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

logger = logging.getLogger(__name__)

############################
# Lock Model Scope
############################
#
# DuckLake advisory locks (this module) protect only DuckLake raw table mutations
# and DuckLake provenance table mutations. They are acquired via PostgreSQL
# pg_advisory_lock and released when the context manager exits.
#
# State NOT protected by these locks:
#   - Raw-object ledger metadata and publication markers (PostgreSQL, managed
#     via raw-object ledger transactions in PublicationTracker).
#   - Raw filesystem files (downloaded archives on disk).
#
# These three systems (DuckLake, PostgreSQL raw-object ledger, raw filesystem)
# are not transactionally coupled to each other. Each has its own consistency
# boundary. See runner.py for the eventual-consistency discussion between
# DuckLake commits and raw-object publication markers.
#
# Lock domains are derived from data and provenance table names only. They do
# not cover publication-scope-level state such as raw-object ledger rows or
# filesystem paths. Any code that mutates non-DuckLake state must not assume
# it is protected by the DuckLake lock.
#
############################


############################
# Lock Domains
############################

DUCKLAKE_MIGRATION_LOCK_DOMAIN = "ducklake:migration"
# NOTE: Reserved placeholder only in case a maintenance lock label is needed later.
DUCKLAKE_MAINTENANCE_LOCK_DOMAIN = "ducklake:maintenance"

_DATA_TABLE_LOCK_DOMAINS = {
    RawDuckLakeTable.MARKET_HISTORY: "ducklake:raw:raw_market_history",
    RawDuckLakeTable.MARKET_ORDERS: "ducklake:raw:raw_market_orders",
    RawDuckLakeTable.FUZZWORK_ORDERS: "ducklake:raw:raw_fuzzwork_orders",
    RawDuckLakeTable.REFERENCE_CATEGORIES: "ducklake:raw:raw_reference_categories",
    RawDuckLakeTable.REFERENCE_GROUPS: "ducklake:raw:raw_reference_groups",
    RawDuckLakeTable.REFERENCE_MARKET_GROUPS: "ducklake:raw:raw_reference_market_groups",
    RawDuckLakeTable.REFERENCE_REGIONS: "ducklake:raw:raw_reference_regions",
    RawDuckLakeTable.REFERENCE_TYPES: "ducklake:raw:raw_reference_types",
}

_PROVENANCE_TABLE_LOCK_DOMAINS = {
    RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS: "ducklake:support:raw_market_history_objects",
    RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS: "ducklake:support:raw_market_orders_objects",
    RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS: "ducklake:support:raw_fuzzwork_orders_objects",
    RawDuckLakeProvenanceTable.REFERENCE_OBJECTS: "ducklake:support:raw_reference_objects",
}

_PUBLICATION_SCOPE_TABLES = {
    "raw:market_history:": (
        (RawDuckLakeTable.MARKET_HISTORY,),
        (RawDuckLakeProvenanceTable.MARKET_HISTORY_OBJECTS,),
    ),
    "raw:market_orders:": (
        (RawDuckLakeTable.MARKET_ORDERS,),
        (RawDuckLakeProvenanceTable.MARKET_ORDERS_OBJECTS,),
    ),
    "raw:fuzzwork_orders:": (
        (RawDuckLakeTable.FUZZWORK_ORDERS,),
        (RawDuckLakeProvenanceTable.FUZZWORK_ORDERS_OBJECTS,),
    ),
    "raw:references:": (
        (
            RawDuckLakeTable.REFERENCE_CATEGORIES,
            RawDuckLakeTable.REFERENCE_GROUPS,
            RawDuckLakeTable.REFERENCE_MARKET_GROUPS,
            RawDuckLakeTable.REFERENCE_REGIONS,
            RawDuckLakeTable.REFERENCE_TYPES,
        ),
        (RawDuckLakeProvenanceTable.REFERENCE_OBJECTS,),
    ),
}

_LOCK_DOMAIN_RANKS = {
    DUCKLAKE_MIGRATION_LOCK_DOMAIN: 0,
    "ducklake:raw:": 1,
    "ducklake:support:": 2,
}


############################
# Errors And Context
############################


class DuckLakeLockTimeoutError(RuntimeError):
    """Raised when a DuckLake advisory lock cannot be acquired in time."""


class DuckLakeLockViolationError(RuntimeError):
    """Raised when a DuckLake mutation is attempted without a matching lock."""


@dataclass(frozen=True)
class DuckLakeLockContext:
    dataset: str | None = None
    publication_scope: str | None = None
    table: str | None = None
    source_date: str | None = None
    airflow_run_id: str | None = None


_DUCKLAKE_LOCK_TOKEN_SENTINEL = object()


############################
# Lock Token
############################


@dataclass(frozen=True, init=False)
class DuckLakeLockToken:
    """Proof that specific DuckLake advisory lock domains are currently held."""

    held_domains: tuple[str, ...]
    # held_domains is immutable; _active is lifecycle state toggled only by the lock context manager.
    _active: bool = field(repr=False, compare=False)

    def __init__(
        self,
        held_domains: Iterable[str],
        *,
        _active: bool = True,
        _sentinel: object | None = None,
    ) -> None:
        if _sentinel is not _DUCKLAKE_LOCK_TOKEN_SENTINEL:
            raise TypeError(
                "DuckLakeLockToken cannot be constructed directly; use "
                "hold_ducklake_lock_domains() or DuckLakeLockToken.unsafe_for_tests()"
            )
        object.__setattr__(self, "held_domains", ordered_ducklake_lock_domains(held_domains))
        object.__setattr__(self, "_active", _active)

    @classmethod
    def unsafe_for_tests(cls, lock_domains: Iterable[str]) -> DuckLakeLockToken:
        return cls(
            lock_domains,
            _active=True,
            _sentinel=_DUCKLAKE_LOCK_TOKEN_SENTINEL,
        )

    @property
    def is_active(self) -> bool:
        return self._active

    def require_data_table(self, table: RawDuckLakeTable) -> None:
        self.require_domain(raw_table_lock_domain(table), table=table.value)

    def require_provenance_table(self, table: RawDuckLakeProvenanceTable) -> None:
        self.require_domain(provenance_table_lock_domain(table), table=table.value)

    def require_domain(self, lock_domain: str, *, table: str | None = None) -> None:
        if not self.is_active:
            raise DuckLakeLockViolationError(
                f"DuckLake lock token is inactive; required domain={lock_domain} held_domains={list(self.held_domains)}"
            )
        if lock_domain in self.held_domains:
            return
        table_context = "" if table is None else f" table={table}"
        raise DuckLakeLockViolationError(
            f"DuckLake lock token does not cover required domain={lock_domain}{table_context}; "
            f"held_domains={list(self.held_domains)}"
        )


############################
# Domain Helpers
############################


def raw_table_lock_domain(table: RawDuckLakeTable) -> str:
    return _DATA_TABLE_LOCK_DOMAINS[table]


def provenance_table_lock_domain(table: RawDuckLakeProvenanceTable) -> str:
    return _PROVENANCE_TABLE_LOCK_DOMAINS[table]


def ducklake_lock_domains_for_tables(
    *,
    data_tables: Iterable[RawDuckLakeTable] = (),
    provenance_tables: Iterable[RawDuckLakeProvenanceTable] = (),
) -> tuple[str, ...]:
    return ordered_ducklake_lock_domains(
        [raw_table_lock_domain(table) for table in data_tables]
        + [provenance_table_lock_domain(table) for table in provenance_tables]
    )


def all_raw_publication_lock_domains() -> tuple[str, ...]:
    return ordered_ducklake_lock_domains(
        tuple(_DATA_TABLE_LOCK_DOMAINS.values()) + tuple(_PROVENANCE_TABLE_LOCK_DOMAINS.values())
    )


def raw_bootstrap_lock_domains() -> tuple[str, ...]:
    return ordered_ducklake_lock_domains((DUCKLAKE_MIGRATION_LOCK_DOMAIN, *all_raw_publication_lock_domains()))


def ducklake_lock_domains_for_publication_scope(publication_scope: str) -> tuple[str, ...]:
    for prefix, (data_tables, provenance_tables) in _PUBLICATION_SCOPE_TABLES.items():
        if publication_scope.startswith(prefix):
            return ducklake_lock_domains_for_tables(data_tables=data_tables, provenance_tables=provenance_tables)
    raise ValueError(f"Unsupported publication scope for DuckLake lock domains: {publication_scope}")


def ordered_ducklake_lock_domains(lock_domains: Iterable[str]) -> tuple[str, ...]:
    unique = tuple(dict.fromkeys(lock_domains))
    return tuple(sorted(unique, key=lambda domain: (_rank(domain), domain)))


def ducklake_lock_key(lock_domain: str) -> int:
    digest = hashlib.blake2b(lock_domain.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


############################
# Lock Acquisition
############################


@contextmanager
def hold_ducklake_lock_domains(
    *,
    catalog_url: str,
    lock_domains: Iterable[str],
    timeout_seconds: float,
    context: DuckLakeLockContext | None = None,
) -> Iterator[DuckLakeLockToken]:
    ordered_domains = ordered_ducklake_lock_domains(lock_domains)
    token = DuckLakeLockToken(
        ordered_domains,
        _active=False,
        _sentinel=_DUCKLAKE_LOCK_TOKEN_SENTINEL,
    )
    if not ordered_domains:
        object.__setattr__(token, "_active", True)
        try:
            yield token
        finally:
            object.__setattr__(token, "_active", False)
        return

    log_context = _context_str(context)

    logger.info(
        "Waiting for DuckLake advisory locks domains=%s timeout_seconds=%s%s",
        list(ordered_domains),
        timeout_seconds,
        log_context,
    )
    with psycopg.connect(postgresql_uri(catalog_url), autocommit=True) as connection:
        timeout_ms = str(int(timeout_seconds * 1000))
        with connection.cursor() as cursor:
            cursor.execute("select set_config('statement_timeout', %s, false)", (timeout_ms,))
            try:
                for lock_domain in ordered_domains:
                    cursor.execute("select pg_advisory_lock(%s)", (ducklake_lock_key(lock_domain),))
                    logger.info("Acquired DuckLake advisory lock domain=%s%s", lock_domain, log_context)
            except psycopg.errors.QueryCanceled as exc:
                raise DuckLakeLockTimeoutError(
                    f"Timed out waiting for DuckLake lock domain(s) after {timeout_seconds} seconds: "
                    f"{', '.join(ordered_domains)}"
                ) from exc
            finally:
                cursor.execute("select set_config('statement_timeout', '0', false)")
        object.__setattr__(token, "_active", True)
        try:
            yield token
        finally:
            object.__setattr__(token, "_active", False)
            logger.info("Releasing DuckLake advisory locks domains=%s%s", list(ordered_domains), log_context)


############################
# Misc Helpers
###########################


def postgresql_uri(url: str) -> str:
    parsed = make_url(url)
    if parsed.drivername.startswith("postgresql"):
        parsed = parsed.set(drivername="postgresql")
    return parsed.render_as_string(hide_password=False)


def _rank(lock_domain: str) -> int:
    if lock_domain in _LOCK_DOMAIN_RANKS:
        return _LOCK_DOMAIN_RANKS[lock_domain]

    for prefix, rank in _LOCK_DOMAIN_RANKS.items():
        if lock_domain.startswith(prefix):
            return rank

    raise ValueError(f"Unsupported DuckLake lock domain: {lock_domain}")


def _context_str(context: DuckLakeLockContext | None) -> str:
    if context is None:
        return ""

    parts = []
    if context.dataset:
        parts.append(f"dataset={context.dataset}")
    if context.publication_scope:
        parts.append(f"publication_scope={context.publication_scope}")
    if context.table:
        parts.append(f"table={context.table}")
    if context.source_date:
        parts.append(f"source_date={context.source_date}")
    if context.airflow_run_id:
        parts.append(f"airflow_run_id={context.airflow_run_id}")

    if not parts:
        return ""
    return " " + " ".join(parts)
