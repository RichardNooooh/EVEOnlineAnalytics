from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import duckdb


@dataclass(frozen=True)
class Publication:
    source_table: str
    target_table: str


PUBLICATIONS = {
    "curated_daily_prices": Publication(
        source_table="mart_curated_daily_prices",
        target_table="curated_daily_prices",
    ),
    "curated_trade_volume": Publication(
        source_table="mart_curated_trade_volume",
        target_table="curated_trade_volume",
    ),
}


def default_local_postgres_attach_path() -> str:
    return (
        "ducklake:postgres:"
        f"dbname={os.environ.get('POSTGRES_DB', 'airflow')} "
        f"host={os.environ.get('DBT_POSTGRES_HOST', '127.0.0.1')} "
        f"port={os.environ.get('POSTGRES_HOST_PORT', '5432')} "
        f"user={os.environ.get('POSTGRES_USER', 'airflow')} "
        f"password={os.environ.get('POSTGRES_PASSWORD', 'airflow-local-only')}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish dbt scratch marts into canonical curated DuckLake tables.",
    )
    parser.add_argument(
        "--db-path",
        default=os.environ.get("DBT_DUCKDB_PATH", "/tmp/eve_market_transform.duckdb"),
        help="Path to the local dbt DuckDB scratch database.",
    )
    parser.add_argument(
        "--ducklake-attach-path",
        default=os.environ.get(
            "CURATED_DUCKLAKE_ATTACH_PATH",
            default_local_postgres_attach_path(),
        ),
        help="Writable curated DuckLake catalog attach path.",
    )
    parser.add_argument(
        "--ducklake-data-path",
        default=os.environ.get(
            "CURATED_DUCKLAKE_DATA_PATH",
            "../.local/data/datasets/ducklake",
        ),
        help="DuckLake data path for the curated publication root.",
    )
    parser.add_argument(
        "--ducklake-alias",
        default=os.environ.get("CURATED_DUCKLAKE_ALIAS", "curated_lake"),
        help="Attached alias used for the writable curated DuckLake.",
    )
    parser.add_argument(
        "--ducklake-schema",
        default=os.environ.get("CURATED_DUCKLAKE_SCHEMA", "curated"),
        help="Schema to publish curated tables into.",
    )
    parser.add_argument(
        "--ducklake-metadata-schema",
        default=os.environ.get("CURATED_DUCKLAKE_METADATA_SCHEMA", "eve_market"),
        help="DuckLake catalog metadata schema.",
    )
    parser.add_argument(
        "--ducklake-override-data-path",
        default=os.environ.get("CURATED_DUCKLAKE_OVERRIDE_DATA_PATH", "1"),
        help="Whether to override the catalog data path for this connection (0 or 1).",
    )
    parser.add_argument(
        "--source-schema",
        default=os.environ.get("CURATED_SOURCE_SCHEMA", "main"),
        help="Schema holding dbt-built scratch tables.",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        choices=sorted(PUBLICATIONS),
        help="Curated dataset to publish. Defaults to all supported datasets.",
    )
    return parser.parse_args()


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def qualified_name(*parts: str) -> str:
    return ".".join(quote_identifier(part) for part in parts)


def coerce_bool_flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def ensure_local_paths(attach_path: str, data_path: str) -> None:
    parsed_attach = attach_path.removeprefix("ducklake:")
    if parsed_attach.startswith("sqlite:"):
        catalog_path = Path(parsed_attach.removeprefix("sqlite:")).expanduser()
        catalog_path.parent.mkdir(parents=True, exist_ok=True)

    parsed_data_path = urlparse(data_path)
    if parsed_data_path.scheme == "file":
        resolved = Path(unquote(parsed_data_path.path)).expanduser()
        resolved.mkdir(parents=True, exist_ok=True)
        return

    if not parsed_data_path.scheme:
        Path(data_path).expanduser().mkdir(parents=True, exist_ok=True)


def attach_curated_ducklake(
    con: duckdb.DuckDBPyConnection,
    *,
    alias: str,
    attach_path: str,
    data_path: str,
    metadata_schema: str,
    override_data_path: bool,
) -> None:
    options = [f"data_path '{data_path}'"]
    if not attach_path.startswith("ducklake:sqlite:") or metadata_schema != "main":
        options.append(f"metadata_schema '{metadata_schema}'")
    if override_data_path:
        options.append(f"override_data_path {str(override_data_path).lower()}")

    sql = f"attach '{attach_path}' as {quote_identifier(alias)} ({', '.join(options)})"
    con.execute(sql)


def assert_relation_exists(
    con: duckdb.DuckDBPyConnection,
    *,
    schema_name: str,
    table_name: str,
) -> None:
    relation_name = qualified_name(schema_name, table_name)
    try:
        con.execute(f"select 1 from {relation_name} limit 1")
    except duckdb.Error as exc:
        msg = f"required dbt scratch table {relation_name} is missing: {exc}"
        raise RuntimeError(msg) from exc


def publish_dataset(
    con: duckdb.DuckDBPyConnection,
    *,
    publication: Publication,
    source_schema: str,
    target_alias: str,
    target_schema: str,
) -> None:
    assert_relation_exists(
        con,
        schema_name=source_schema,
        table_name=publication.source_table,
    )
    con.execute(
        f"create schema if not exists {qualified_name(target_alias, target_schema)}"
    )
    con.execute(
        "create or replace table "
        f"{qualified_name(target_alias, target_schema, publication.target_table)} as "
        f"select * from {qualified_name(source_schema, publication.source_table)}"
    )


def selected_publications(dataset_names: list[str] | None) -> list[Publication]:
    names = dataset_names or list(PUBLICATIONS)
    return [PUBLICATIONS[name] for name in names]


def main() -> int:
    args = parse_args()
    ensure_local_paths(args.ducklake_attach_path, args.ducklake_data_path)

    con = duckdb.connect(args.db_path)
    try:
        if args.ducklake_attach_path.startswith("ducklake:postgres:"):
            con.execute("install postgres")
            con.execute("load postgres")
        con.execute("install ducklake")
        con.execute("load ducklake")
        attach_curated_ducklake(
            con,
            alias=args.ducklake_alias,
            attach_path=args.ducklake_attach_path,
            data_path=args.ducklake_data_path,
            metadata_schema=args.ducklake_metadata_schema,
            override_data_path=coerce_bool_flag(args.ducklake_override_data_path),
        )
        for publication in selected_publications(args.dataset):
            publish_dataset(
                con,
                publication=publication,
                source_schema=args.source_schema,
                target_alias=args.ducklake_alias,
                target_schema=args.ducklake_schema,
            )
    finally:
        con.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
