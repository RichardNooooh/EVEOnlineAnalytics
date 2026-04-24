# Local Airflow Development

Local-only Airflow + dlt demo stack. It does not replace k3s or Helm deployment.

## Services

- Airflow `3.2.1` with `LocalExecutor`
- Postgres metadata database
- Mounted repo directories for DAGs, ingestion, dbt, contracts, local published data, and logs

## Mounts

| Host path | Container path | Purpose |
|---|---|---|
| `orchestration/dags` | `/opt/airflow/dags` | Airflow DAGs |
| `ingestion` | `/opt/eve-market/ingestion` | Project ingestion code |
| `transform` | `/opt/eve-market/transform` | dbt project code |
| `datasets` | `/opt/eve-market/datasets` | Dataset contracts and manifests |
| `.local/data` | `/opt/eve-market/data` | Local published data stand-in for NFS |
| `.local/logs` | `/opt/airflow/logs` | Airflow logs |

## Start

```bash
cp infra/local/.env.example infra/local/.env
make local-airflow-up
```

Open Airflow at <http://localhost:8080>. Default local login is `admin` / `admin` unless changed in `infra/local/.env`.

## Stop

```bash
make local-airflow-down
```

## Reset

This deletes local Airflow metadata volume plus `.local/data` and `.local/logs`.

```bash
make local-airflow-reset CONFIRM=yes
```

## Smoke Check

```bash
make local-pipeline-smoke
```

Smoke check verifies Airflow metadata DB connectivity, importable Airflow/dlt/dbt/DuckDB dependencies, and expected mount roots.

## Notes

- Keep real secrets out of git. Commit only `.env.example`.
- Published datasets for this stack live under `.local/data`, not shared NFS.
- DuckDB files created by local experiments must stay local or scratch-only.
- Production Airflow remains managed by `infra/helm/airflow.yml` on k3s.
