import os
from datetime import datetime, timedelta

from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import Param, dag
from docker.types import Mount

DATA_ROOT = "/opt/eve-market/data"
DLT_SCRATCH_ROOT = "/scratch"
INGESTION_IMAGE = os.environ.get(
    "EVE_MARKET_INGESTION_IMAGE", "eve-market-ingestion:local"
)
LOCAL_DATA_HOST_PATH = os.environ.get(
    "EVE_MARKET_LOCAL_DATA_HOST_PATH", "/home/rnoh/dev/eve-market/.local/data"
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
            "postgresql://raw_files:password@postgres:5432/raw_files",
            "--ducklake-catalog",
            "postgresql://airflow:airflow-local-only@postgres:5432/airflow",
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
        mounts=[Mount(source=LOCAL_DATA_HOST_PATH, target=DATA_ROOT, type="bind")],
        force_pull=True,
        auto_remove="success",
        retries=0,
        retry_delay=timedelta(minutes=5),
        execution_timeout=timedelta(hours=2),
    )


backfill_market_history()
