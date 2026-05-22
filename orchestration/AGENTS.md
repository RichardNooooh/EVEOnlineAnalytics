# orchestration/AGENTS.md

Read this when changing Airflow DAGs, orchestration includes, plugins, schedules, or
task dependencies.

## Read First

- `../AGENTS.md`
- `../ingestion/AGENTS.md` for ingestion DAGs
- `../transform/AGENTS.md` for dbt DAGs
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

## Deployment Notes

- Airflow metadata uses an external PostgreSQL service managed by the platform repo.
- Production deployment configuration belongs in `homelab-data-platform`.
- Airflow logs may live on shared NFS.
