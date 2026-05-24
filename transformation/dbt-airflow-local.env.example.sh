#!/usr/bin/env sh

# Source this file from transformation/ when testing dbt against the local
# Airflow-backed DuckLake publication.
#
# This uses the repo's local demo credentials and repo-root published dataset path
# for host-side dbt against the local Airflow-backed publication.

export DBT_DUCKDB_PATH="/tmp/eve_market_transform.duckdb"
export DBT_THREADS="4"
export DBT_DUCKLAKE_ALIAS="raw_lake"
export DBT_DUCKLAKE_ATTACH_PATH="ducklake:postgres:dbname=airflow host=127.0.0.1 port=5432 user=airflow password=airflow-local-only"
export DBT_DUCKLAKE_DATA_PATH="../.local/data/datasets/ducklake/raw/raw_market_history"
export DBT_DUCKLAKE_METADATA_SCHEMA="eve_market"
export DBT_DUCKLAKE_OVERRIDE_DATA_PATH="1"

export CURATED_DUCKLAKE_ATTACH_PATH="ducklake:postgres:dbname=airflow host=127.0.0.1 port=5432 user=airflow password=airflow-local-only"
export CURATED_DUCKLAKE_DATA_PATH="../.local/data/datasets/ducklake"
export CURATED_DUCKLAKE_ALIAS="curated_lake"
export CURATED_DUCKLAKE_SCHEMA="curated"
export CURATED_DUCKLAKE_METADATA_SCHEMA="eve_market"
export CURATED_DUCKLAKE_OVERRIDE_DATA_PATH="1"
