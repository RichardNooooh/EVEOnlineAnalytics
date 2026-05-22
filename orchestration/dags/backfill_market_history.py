import os
from datetime import datetime, timedelta

from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import Param, dag
from docker.types import Mount

DATA_ROOT = "/opt/eve-market/data"
DLT_SCRATCH_ROOT = "/scratch"
DEFAULT_LOCAL_DATA_HOST_PATH = "/tmp/eve-market-local-data"
POSTGRES_HOST = os.environ.get("EVE_MARKET_LOCAL_POSTGRES_HOST", "postgres")
INGESTION_IMAGE = os.environ.get(
    "EVE_MARKET_INGESTION_IMAGE", "eve-market-ingestion:local"
)


def local_data_host_path() -> str:
    """Return host path used by local DockerOperator bind mounts."""
    local_data_host_path = os.environ.get("EVE_MARKET_LOCAL_DATA_HOST_PATH")
    if local_data_host_path:
        return local_data_host_path

    # Keep DAG importable outside the local compose harness without relying on
    # a machine-specific checkout path. Local review flows should override this
    # to the repo's `.local/data` host path.
    return DEFAULT_LOCAL_DATA_HOST_PATH


def should_force_pull(image: str) -> bool:
    """Skip pulls for the default local image tag."""
    return image != "eve-market-ingestion:local"


def raw_ledger_url() -> str:
    """Return local raw ledger URL with env-overridable credentials."""
    return os.environ.get(
        "EVE_MARKET_RAW_LEDGER_URL",
        (
            "postgresql://raw_files:"
            f"{os.environ.get('RAW_FILES_POSTGRES_PASSWORD', 'password')}"
            f"@{POSTGRES_HOST}:5432/raw_files"
        ),
    )


def ducklake_catalog_url() -> str:
    """Return local DuckLake catalog URL with env-overridable credentials."""
    return os.environ.get(
        "EVE_MARKET_DUCKLAKE_CATALOG",
        (
            f"postgresql://{os.environ.get('POSTGRES_USER', 'airflow')}:"
            f"{os.environ.get('POSTGRES_PASSWORD', 'airflow-local-only')}"
            f"@{POSTGRES_HOST}:5432/{os.environ.get('POSTGRES_DB', 'airflow')}"
        ),
    )


@dag(
    dag_id="backfill_market_history",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["ingestion", "everef", "market-history", "backfill"],
    params={
        "start_date": Param("2025-01-01", type="string"),
        "end_date": Param("2025-01-01", type="string"),
    },
)
def backfill_market_history():
    """
    ## Backfill Market History
    """
    DockerOperator(
        task_id="sync_raw_market_history",
        image=INGESTION_IMAGE,
        command=[
            "everef",
            "run-pipeline",
            "--start-date",
            "{{ params.start_date }}",
            "--end-date",
            "{{ params.end_date }}",
            "--sync-raw",
            "--storage-target",
            "mounted",
            "--data-root",
            DATA_ROOT,
            "--raw-ledger-url",
            raw_ledger_url(),
            "--ducklake-catalog",
            ducklake_catalog_url(),
        ],
        docker_url="unix://var/run/docker.sock",
        network_mode="eve-market-airflow-local",
        environment={
            "HOME": f"{DLT_SCRATCH_ROOT}/home",
            "TMPDIR": f"{DLT_SCRATCH_ROOT}/tmp",
            "EVE_DLT_STATE_DIR": f"{DLT_SCRATCH_ROOT}/dlt",
            "DLT_DATA_DIR": f"{DLT_SCRATCH_ROOT}/dlt",
            "DLT_LOCAL_DIR": f"{DLT_SCRATCH_ROOT}/local",
        },
        mount_tmp_dir=False,
        mounts=[
            Mount(
                source=local_data_host_path(),
                target=DATA_ROOT,
                type="bind",
            )
        ],
        force_pull=should_force_pull(INGESTION_IMAGE),
        auto_remove="success",
        retries=0,
        retry_delay=timedelta(minutes=5),
        execution_timeout=timedelta(hours=2),
    )


backfill_market_history()
