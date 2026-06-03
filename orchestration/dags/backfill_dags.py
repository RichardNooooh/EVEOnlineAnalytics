from typing import TypedDict

from eve_market_airflow.dag_utils import build_backfill_dag


class BackfillDagConfig(TypedDict):
    dag_id: str
    command_name: str
    tags: list[str]
    has_date_range: bool


_DAG_CONFIGS: list[BackfillDagConfig] = [
    {
        "dag_id": "backfill_market_orders",
        "command_name": "market-orders",
        "tags": ["ingestion", "everef", "market-orders", "backfill"],
        "has_date_range": True,
    },
    {
        "dag_id": "backfill_market_history",
        "command_name": "market-history",
        "tags": ["ingestion", "everef", "market-history", "backfill"],
        "has_date_range": True,
    },
    {
        "dag_id": "backfill_fuzzwork_orders",
        "command_name": "fuzzwork-orders",
        "tags": ["ingestion", "everef", "fuzzwork-orders", "backfill"],
        "has_date_range": True,
    },
    {
        "dag_id": "backfill_references",
        "command_name": "references",
        "tags": ["ingestion", "everef", "references", "backfill"],
        "has_date_range": False,
    },
]

for config in _DAG_CONFIGS:
    dag_id = config["dag_id"]
    globals()[dag_id] = build_backfill_dag(
        dag_id=dag_id,
        command_name=config["command_name"],
        tags=config["tags"],
        has_date_range=config["has_date_range"],
    )
