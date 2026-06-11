from eve_market_airflow.dag_utils import build_bootstrap_backfill_dag

bootstrap_backfill_all = build_bootstrap_backfill_dag(
    dag_id="bootstrap_backfill_all",
    tags=["ingestion", "everef", "ducklake", "bootstrap", "backfill"],
)
