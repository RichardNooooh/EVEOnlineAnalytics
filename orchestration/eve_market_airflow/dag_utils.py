from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import Param, dag
from docker.types import Mount

DATA_ROOT = "/opt/eve-market/data"
DLT_SCRATCH_ROOT = "/scratch"
DEFAULT_LOCAL_DATA_HOST_PATH = "/tmp/eve-market-local-data"
POSTGRES_HOST = os.environ.get("EVE_MARKET_LOCAL_POSTGRES_HOST", "postgres")
INGESTION_IMAGE = os.environ.get("EVE_MARKET_INGESTION_IMAGE", "eve-market-ingestion:local")


def local_data_host_path() -> str:
    local_data_host_path = os.environ.get("EVE_MARKET_LOCAL_DATA_HOST_PATH")
    if local_data_host_path:
        return local_data_host_path
    return DEFAULT_LOCAL_DATA_HOST_PATH


def should_force_pull() -> bool:
    return os.environ.get("EVE_MARKET_INGESTION_FORCE_PULL", "false").lower() == "true"


def raw_ledger_url() -> str:
    return os.environ.get(
        "EVE_MARKET_RAW_LEDGER_URL",
        (
            "postgresql://raw_files:"
            f"{os.environ.get('RAW_FILES_POSTGRES_PASSWORD', 'password')}"
            f"@{POSTGRES_HOST}:5432/raw_files"
        ),
    )


def ducklake_catalog_url() -> str:
    return os.environ.get(
        "EVE_MARKET_DUCKLAKE_CATALOG",
        (
            f"postgresql://{os.environ.get('POSTGRES_USER', 'airflow')}:"
            f"{os.environ.get('POSTGRES_PASSWORD', 'airflow-local-only')}"
            f"@{POSTGRES_HOST}:5432/{os.environ.get('POSTGRES_DB', 'airflow')}"
        ),
    )


def ducklake_lock_wait_timeout_seconds() -> str:
    return os.environ.get("EVE_DUCKLAKE_LOCK_WAIT_TIMEOUT_SECONDS", "60")


def ducklake_pg_pool_max_connections() -> str:
    return os.environ.get("EVE_DUCKLAKE_PG_POOL_MAX_CONNECTIONS", "32")


def ducklake_pg_pool_wait_timeout_millis() -> str:
    return os.environ.get("EVE_DUCKLAKE_PG_POOL_WAIT_TIMEOUT_MILLIS", "120000")


def ducklake_pg_pool_acquire_mode() -> str:
    return os.environ.get("EVE_DUCKLAKE_PG_POOL_ACQUIRE_MODE", "wait")


def shared_ingestion_command_args() -> list[str]:
    return [
        "--data-root",
        DATA_ROOT,
        "--raw-ledger-url",
        raw_ledger_url(),
        "--ducklake-catalog",
        ducklake_catalog_url(),
        "--ducklake-metadata-schema",
        "eve_market",
        "--ducklake-pg-pool-max-connections",
        ducklake_pg_pool_max_connections(),
        "--ducklake-pg-pool-wait-timeout-millis",
        ducklake_pg_pool_wait_timeout_millis(),
        "--ducklake-pg-pool-acquire-mode",
        ducklake_pg_pool_acquire_mode(),
    ]


def build_ingestion_task(*, task_id: str, command: list[str]) -> DockerOperator:
    return DockerOperator(
        task_id=task_id,
        image=INGESTION_IMAGE,
        command=command,
        docker_url="unix://var/run/docker.sock",
        network_mode="eve-market-airflow-local",
        environment={
            "HOME": f"{DLT_SCRATCH_ROOT}/home",
            "TMPDIR": f"{DLT_SCRATCH_ROOT}/tmp",
            "INGEST_LOG_LEVEL": os.environ.get("INGEST_LOG_LEVEL", "DEBUG"),
            "EVE_DLT_STATE_DIR": f"{DLT_SCRATCH_ROOT}/dlt",
            "DLT_DATA_DIR": f"{DLT_SCRATCH_ROOT}/dlt",
            "DLT_LOCAL_DIR": f"{DLT_SCRATCH_ROOT}/local",
            "EVE_DUCKLAKE_LOCK_WAIT_TIMEOUT_SECONDS": ducklake_lock_wait_timeout_seconds(),
            "EVE_DUCKLAKE_PG_POOL_MAX_CONNECTIONS": ducklake_pg_pool_max_connections(),
            "EVE_DUCKLAKE_PG_POOL_WAIT_TIMEOUT_MILLIS": ducklake_pg_pool_wait_timeout_millis(),
            "EVE_DUCKLAKE_PG_POOL_ACQUIRE_MODE": ducklake_pg_pool_acquire_mode(),
        },
        mount_tmp_dir=False,
        mounts=[
            Mount(
                source=local_data_host_path(),
                target=DATA_ROOT,
                type="bind",
            )
        ],
        force_pull=should_force_pull(),
        auto_remove="success",
        retries=0,
        retry_delay=timedelta(minutes=5),
        execution_timeout=timedelta(hours=2),
    )


def build_backfill_dag(
    *,
    dag_id: str,
    command_name: str,
    tags: list[str],
    has_date_range: bool = True,
):
    command = ["everef", command_name]
    if has_date_range:
        command.extend(
            [
                "--start-date",
                "{{ params.start_date }}",
                "--end-date",
                "{{ params.end_date }}",
            ]
        )
    command.extend(shared_ingestion_command_args())

    task_id = f"sync_raw_{command_name.replace('-', '_')}"

    params = (
        {
            "start_date": Param("2026-01-01", type="string"),
            "end_date": Param("2026-01-01", type="string"),
        }
        if has_date_range
        else None
    )

    @dag(
        dag_id=dag_id,
        schedule=None,
        start_date=datetime(2026, 1, 1),
        catchup=False,
        # Scheduler-level serialization reduces accidental overlap, but the writer-side
        # PostgreSQL advisory lock domains remain the concurrency source of truth.
        max_active_runs=1,
        tags=tags,
        params=params,
    )
    def _backfill():
        build_ingestion_task(task_id=task_id, command=command)

    return _backfill()


def build_bootstrap_backfill_dag(*, dag_id: str, tags: list[str]):
    params = {
        "start_date": Param("2026-01-01", type="string"),
        "end_date": Param("2026-01-01", type="string"),
    }

    @dag(
        dag_id=dag_id,
        schedule=None,
        start_date=datetime(2026, 1, 1),
        catchup=False,
        # Scheduler-level serialization reduces accidental overlap, but the writer-side
        # PostgreSQL advisory lock domains remain the concurrency source of truth.
        max_active_runs=1,
        tags=tags,
        params=params,
    )
    def _bootstrap_backfill():
        bootstrap_raw = build_ingestion_task(
            task_id="bootstrap_raw_ducklake",
            command=["ducklake", "bootstrap", "raw", *shared_ingestion_command_args()],
        )
        market_orders = build_ingestion_task(
            task_id="sync_raw_market_orders",
            command=[
                "everef",
                "market-orders",
                "--start-date",
                "{{ params.start_date }}",
                "--end-date",
                "{{ params.end_date }}",
                *shared_ingestion_command_args(),
            ],
        )
        market_history = build_ingestion_task(
            task_id="sync_raw_market_history",
            command=[
                "everef",
                "market-history",
                "--start-date",
                "{{ params.start_date }}",
                "--end-date",
                "{{ params.end_date }}",
                *shared_ingestion_command_args(),
            ],
        )
        fuzzwork_orders = build_ingestion_task(
            task_id="sync_raw_fuzzwork_orders",
            command=[
                "everef",
                "fuzzwork-orders",
                "--start-date",
                "{{ params.start_date }}",
                "--end-date",
                "{{ params.end_date }}",
                *shared_ingestion_command_args(),
            ],
        )
        references = build_ingestion_task(
            task_id="sync_raw_references",
            command=["everef", "references", *shared_ingestion_command_args()],
        )

        bootstrap_raw >> [market_orders, market_history, fuzzwork_orders, references]

    return _bootstrap_backfill()
