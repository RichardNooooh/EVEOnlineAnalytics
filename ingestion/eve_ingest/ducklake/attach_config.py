from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlparse

from eve_ingest.util import DEFAULT_DUCKLAKE_CATALOG, DEFAULT_DUCKLAKE_METADATA_SCHEMA, DEFAULT_DUCKLAKE_RAW_DATA_PATH

logger = logging.getLogger(__name__)

DEFAULT_DUCKLAKE_ALIAS = "ducklake"
DEFAULT_RAW_SCHEMA = "raw"


@dataclass(frozen=True)
class DuckLakeAttachConfig:
    """Resolved DuckLake attachment settings for one writable target."""

    attach_uri: str
    data_path: str
    metadata_schema: str = "main"
    alias: str = DEFAULT_DUCKLAKE_ALIAS
    override_data_path: bool = True
    postgres_pool_max_connections: int | None = None
    postgres_pool_wait_timeout_millis: int | None = None
    postgres_pool_acquire_mode: str | None = None


def build_ducklake_attach_config_from_url(
    postgres_url: str,
    *,
    data_path: str | None = None,
    metadata_schema: str | None = None,
    alias: str | None = None,
    postgres_pool_max_connections: int | None = None,
    postgres_pool_wait_timeout_millis: int | None = None,
    postgres_pool_acquire_mode: str | None = None,
) -> DuckLakeAttachConfig:
    """Build a DuckLakeAttachConfig from an arbitrary PostgreSQL URL.

    Args:
        postgres_url: PostgreSQL URL for the DuckLake catalog.
        data_path: Override the default raw data path.
        metadata_schema: Override the default metadata schema.
        alias: Override the default alias.
    """
    parsed = urlparse(postgres_url)
    scheme = parsed.scheme.split("+")[0]
    if scheme not in {"postgres", "postgresql"}:
        raise ValueError("ducklake_catalog must be a PostgreSQL URL")
    if not parsed.hostname:
        raise ValueError("ducklake_catalog must include a host")
    if parsed.path in {"", "/"}:
        raise ValueError("ducklake_catalog must include a database name")

    parts = [f"dbname={parsed.path.removeprefix('/')}", f"host={parsed.hostname}"]
    if parsed.port is not None:
        parts.append(f"port={parsed.port}")
    if parsed.username is not None:
        parts.append(f"user={unquote(parsed.username)}")
    if parsed.password is not None:
        parts.append(f"password={unquote(parsed.password)}")

    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        parts.append(f"{key}={value}")

    return DuckLakeAttachConfig(
        attach_uri="ducklake:postgres:" + " ".join(parts),
        data_path=data_path or DEFAULT_DUCKLAKE_RAW_DATA_PATH,
        metadata_schema=metadata_schema or DEFAULT_DUCKLAKE_METADATA_SCHEMA,
        alias=alias or DEFAULT_DUCKLAKE_ALIAS,
        postgres_pool_max_connections=postgres_pool_max_connections,
        postgres_pool_wait_timeout_millis=postgres_pool_wait_timeout_millis,
        postgres_pool_acquire_mode=postgres_pool_acquire_mode,
    )


def _build_default_attach_config() -> DuckLakeAttachConfig:
    return build_ducklake_attach_config_from_url(DEFAULT_DUCKLAKE_CATALOG)
