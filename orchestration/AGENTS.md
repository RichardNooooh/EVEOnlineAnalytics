# orchestration/AGENTS.md

Read this when changing Airflow DAGs, orchestration includes, plugins, schedules, or
task dependencies.

## Read First

- `../AGENTS.md`
- `../ingestion/AGENTS.md` for ingestion DAGs
- `../transform/AGENTS.md` for dbt DAGs
- `../infra/AGENTS.md` for deployment/runtime assumptions

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

- Airflow metadata uses an external PostgreSQL server on its own Proxmox VM.
- Helm values should live at `../infra/helm/airflow.yml` when checked in.
- Airflow logs may live on shared NFS.
