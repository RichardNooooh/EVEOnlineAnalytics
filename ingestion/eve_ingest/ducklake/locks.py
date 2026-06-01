from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
from sqlalchemy.engine import make_url

logger = logging.getLogger("eve_ingest.ducklake")

DUCKLAKE_MIGRATION_LOCK_DOMAIN = "ducklake:migration"
DUCKLAKE_MAINTENANCE_LOCK_DOMAIN = "ducklake:maintenance"

_DATASET_LOCK_DOMAINS = {
    "raw:market_history:": (
        "ducklake:raw:raw_market_history",
        "ducklake:support:raw_market_history_objects",
    ),
    "raw:market_orders:": (
        "ducklake:raw:raw_market_orders",
        "ducklake:support:raw_market_orders_objects",
    ),
    "raw:fuzzwork_orders:": (
        "ducklake:raw:raw_fuzzwork_orders",
        "ducklake:support:raw_fuzzwork_orders_objects",
    ),
    "raw:references:": (
        "ducklake:raw:references",
        "ducklake:support:raw_reference_objects",
    ),
}

_LOCK_DOMAIN_RANKS = {
    DUCKLAKE_MIGRATION_LOCK_DOMAIN: 0,
    DUCKLAKE_MAINTENANCE_LOCK_DOMAIN: 1,
    "ducklake:raw:": 2,
    "ducklake:support:": 3,
}


class DuckLakeLockTimeoutError(RuntimeError):
    """Raised when a DuckLake advisory lock cannot be acquired in time."""


@dataclass(frozen=True)
class DuckLakeLockContext:
    dataset: str | None = None
    publication_scope: str | None = None
    table: str | None = None
    source_date: str | None = None
    airflow_run_id: str | None = None


def ducklake_lock_domains_for_publication_scope(publication_scope: str) -> tuple[str, ...]:
    for prefix, domains in _DATASET_LOCK_DOMAINS.items():
        if publication_scope.startswith(prefix):
            return domains
    raise ValueError(f"Unsupported publication scope for DuckLake lock domains: {publication_scope}")


def ordered_ducklake_lock_domains(lock_domains: Iterable[str]) -> tuple[str, ...]:
    unique = tuple(dict.fromkeys(lock_domains))
    return tuple(sorted(unique, key=lambda domain: (_ducklake_lock_rank(domain), domain)))


def ducklake_lock_key(lock_domain: str) -> int:
    digest = hashlib.blake2b(lock_domain.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


@contextmanager
def hold_ducklake_lock_domains(
    *,
    catalog_url: str,
    lock_domains: Iterable[str],
    timeout_seconds: float,
    context: DuckLakeLockContext | None = None,
) -> Iterator[None]:
    ordered_domains = ordered_ducklake_lock_domains(lock_domains)
    if not ordered_domains:
        yield
        return

    log_context = _ducklake_lock_log_context(context)

    logger.info(
        "Waiting for DuckLake advisory locks domains=%s timeout_seconds=%s%s",
        list(ordered_domains),
        timeout_seconds,
        log_context,
    )
    connection = psycopg.connect(postgresql_uri(catalog_url), autocommit=True)
    try:
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
        yield
    finally:
        logger.info("Releasing DuckLake advisory locks domains=%s%s", list(ordered_domains), log_context)
        connection.close()


def postgresql_uri(url: str) -> str:
    parsed = make_url(url)
    if parsed.drivername.startswith("postgresql"):
        parsed = parsed.set(drivername="postgresql")
    return parsed.render_as_string(hide_password=False)


def _ducklake_lock_rank(lock_domain: str) -> int:
    if lock_domain in _LOCK_DOMAIN_RANKS:
        return _LOCK_DOMAIN_RANKS[lock_domain]

    for prefix, rank in _LOCK_DOMAIN_RANKS.items():
        if lock_domain.startswith(prefix):
            return rank

    raise ValueError(f"Unsupported DuckLake lock domain: {lock_domain}")


def _ducklake_lock_log_context(context: DuckLakeLockContext | None) -> str:
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
