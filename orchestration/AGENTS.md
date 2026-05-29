# orchestration/AGENTS.md

Read this when changing Airflow DAGs, orchestration includes, plugins, schedules, or
task dependencies.

## Read First

- `../AGENTS.md`
- `../ingestion/AGENTS.md` for ingestion DAGs
- `../transformation/AGENTS.md` for dbt DAGs
- `../docs/architecture.md` for deployment/runtime assumptions
- `../infra/local/README.md` for the local analytics harness

## Airflow Role

- Airflow schedules ingestion, transforms, training, predictions, and monitoring.
- Ingestion tasks run Python + dlt source-specific pipelines.
- Transform tasks run dbt with local/transient DuckDB work databases only.
- Training and model jobs should use MLflow for experiment tracking when implemented.
- Monitoring jobs should use Evidently for data and prediction drift when implemented.

## Runtime Rules

- Do not mount shared RWX storage for writable DuckDB work databases.
- Use shared NFS only for DuckLake data files, contracts/manifests, artifacts, and logs.
- Keep publication scopes single-writer.
- Respect ESI rate limits and `Expires` headers in scheduled ingestion.

## Backfill DAG Structure

Backfill DAGs use a shared factory pattern to eliminate duplication:

- `include/dag_utils.py` — shared constants, helpers (`local_data_host_path()`, `raw_ledger_url()`, etc.), and `build_backfill_dag()` factory.
- `dags/backfill_dags.py` — single file that registers all backfill DAGs via a config list + `globals()` loop.
- `dags/.airflowignore` — excludes `include/` from DAG bag parsing.

To add a new backfill DAG, append a config dict to `_DAG_CONFIGS` in `dags/backfill_dags.py`.
Set `has_date_range: False` for sources that don't accept `--start-date`/`--end-date` args (e.g., references).

## Deployment Notes

- Airflow metadata uses an external PostgreSQL service managed by the platform repo.
- Production deployment configuration belongs in `homelab-data-platform`.
- Airflow logs may live on shared NFS.
