# Local Airflow Development

Local-only Airflow + dlt development and demo stack. It supports fast ingestion
iteration and portfolio demos without Proxmox, k3s, TrueNAS, or Helm.

This stack is not production. It does not replace the canonical k3s + Helm deployment
or the TrueNAS-backed DuckLake storage contract.

## Production Mapping

| Local runtime | Production approximation |
|---|---|
| `.local/data` | TrueNAS NFS DuckLake data-file storage |
| local Postgres service | Airflow metadata PostgreSQL |
| bind-mounted DAGs and project code | deployed Airflow image or DAG/code sync mechanism |
| `eve-market-ingestion:local` job image | `ghcr.io/<owner>/eve-market-ingestion:<immutable-tag>` for KubernetesPodOperator |

## Services

- Airflow version from `infra/local/versions.txt` with `LocalExecutor`
- Postgres metadata database
- Mounted repo directories for DAGs, ingestion, dbt, contracts, local published data, and logs
- Docker socket mount for local-only `DockerOperator` task containers

`orchestration/dags` is mounted when present. The directory is part of the target repo
layout, but no DAGs are tracked yet.

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
Change local Airflow and Python image versions in `infra/local/versions.txt`.

Build the ingestion task image used by local `DockerOperator` DAGs:

```bash
make ingestion-image
```

If the Airflow container cannot reach Docker, set `DOCKER_GID` in `infra/local/.env` to
the host Docker group ID from `getent group docker | cut -d: -f3`.

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

Smoke check the local DockerOperator path:

```bash
make local-airflow-docker-smoke
```

## Development Loop

1. edit ingestion and dlt code
2. run locally
3. validate through local Airflow
4. commit
5. validate in CI and publish GHCR image tags from trusted `master` builds
6. deploy to k3s

## Notes

- Keep real secrets out of git. Commit only `.env.example`.
- Published datasets for this stack live under `.local/data`, not shared NFS.
- DuckDB files created by local experiments must stay local or scratch-only.
- The Docker socket mount gives Airflow local control over the host Docker daemon. Keep
  this local-only; do not use this pattern in k3s.
- Production Airflow remains managed by `infra/helm/airflow.yml` on k3s.
- Production DAGs should use `KubernetesPodOperator` with immutable GHCR image tags from
  the `Ingestion Image` workflow, not local Docker socket access.
