# Local Airflow Development

Local-only Airflow + dlt development and published-data demo stack. It supports
fast ingestion iteration and portfolio demos without Proxmox, k3s, TrueNAS, or
Helm.

This stack is not production. It does not replace the production-style runtime
or the TrueNAS-backed DuckLake storage contract. Production-style deployment is
managed in `homelab-data-platform`.

The canonical cross-repo runtime boundary for this local harness and the
production-style platform repo lives in `docs/runtime_contract.md`.

Compose-run BI app lives separately under repo-root `bi/`. This `infra/local/`
harness publishes local DuckLake state that the Evidence app reads as read-only
consumer.

## Production Mapping

| Local runtime | Production approximation |
|---|---|
| `.local/data` | TrueNAS NFS DuckLake data-file storage |
| local Postgres service | Airflow metadata PostgreSQL plus separate `raw_files` ledger database |
| bind-mounted DAGs and project code | deployed Airflow image or DAG/code sync mechanism |
| `eve-market-ingestion:local` job image | `ghcr.io/<owner>/eve-market-ingestion:<immutable-tag>` for KubernetesPodOperator |

## Services

- Airflow version from `infra/local/versions.txt` with `LocalExecutor`
- Postgres metadata database
- Raw file ledger database named `raw_files` with `raw_files` user
- Evidence BI service behind Compose `bi` profile
- Mounted repo directories for DAGs, ingestion, dbt, contracts, local published data, and logs
- Docker socket mount for local-only `DockerOperator` task containers

`orchestration/dags` is mounted directly from this repo so local Airflow sees the same
checked-in DAG code used for workload development.

## Mounts

| Host path | Container path | Purpose |
|---|---|---|
| `orchestration/dags` | `/opt/airflow/dags` | Airflow DAGs |
| `ingestion` | `/opt/eve-market/ingestion` | Project ingestion code |
| `transformation` | `/opt/eve-market/transform` | dbt project code |
| `datasets` | `/opt/eve-market/datasets` | Dataset contracts and manifests |
| `.local/data` | `/opt/eve-market/data` | Local published data stand-in for NFS |
| `.local/logs` | `/opt/airflow/logs` | Airflow logs |

This `.local/data` mount is for published DuckLake data only. Containerized `dlt`
runtime state should use explicit ephemeral scratch separate from shared or durable
storage. Current ingestion image defaults that scratch to `/scratch/dlt` for pipeline
state and `/scratch/local` for local runtime artifacts.
If you want reviewer-style local published data for transform work, publish it through
this stack so dataset files land under repo-root `.local/data`. Host-side dbt is the
supported local exception outside Compose; it attaches to the matching PostgreSQL-backed
DuckLake catalog while keeping its scratch DuckDB on host-local storage.

## Start

```bash
cp infra/local/.env.example infra/local/.env
mise run airflow:up
```

Open Airflow at <http://localhost:8080>. Default local login is `admin` / `admin` unless changed in `infra/local/.env`.
Change local Airflow and Python image versions in `infra/local/versions.txt`.
This harness uses the stock `apache/airflow` reference image.
The local Postgres service is also published to the host by default at
`127.0.0.1:5432` as supported host-dbt exception so dbt can attach to the
reviewer-stack DuckLake catalog.
If that port is already in use, set `POSTGRES_HOST_PORT` in `infra/local/.env`.

Start local Evidence BI through Compose profile `bi`:

```bash
mise run bi:up
```

Open local BI at <http://localhost:3000> in host browser. Compose serves Evidence
from container; browser entrypoint stays local.

Build the ingestion task image used by local `DockerOperator` DAGs:

```bash
mise run ingestion:image
```

Local DAGs default to `eve-market-ingestion:local`. Set
`EVE_MARKET_INGESTION_IMAGE` in `infra/local/.env` if you need to test a different
tag.

Local Airflow also includes a manual `bootstrap_backfill_all` DAG. It runs raw
DuckLake bootstrap first, then fans out to market orders, market history,
fuzzwork orders, and references using one shared `start_date` / `end_date`
parameter set for the date-range tasks. The existing per-dataset backfill DAGs
remain available for targeted reruns.

Set `EVE_MARKET_INGESTION_FORCE_PULL=true` in `infra/local/.env` only when you
want Airflow to pull the configured image before each task run. Leave it `false`
for the default local `eve-market-ingestion:local` workflow so DockerOperator uses
your freshly built local image instead of trying to pull a same-named remote tag.

Set `EVE_MARKET_LOCAL_DATA_HOST_PATH` in `infra/local/.env` to the host path for
this repo's `.local/data` directory. `DockerOperator` bind mounts are evaluated by
the host Docker daemon, not from inside the Airflow container, so child task
containers need that explicit host path to persist DuckLake data files.

Local mounted data is owned by `INGESTION_APP_UID`/`INGESTION_APP_GID` so the
ingestion image can create `/opt/eve-market/data/raw` and DuckLake files during a
backfill. The local harness also opens write permissions on that tree so supported host
dbt can publish curated DuckLake tables into the same mounted path. Keep
`INGESTION_APP_UID`/`INGESTION_APP_GID` aligned with the `ingestion/Dockerfile` runtime
user.

If the Airflow container cannot reach Docker, set `DOCKER_GID` in `infra/local/.env` to
the host Docker group ID from `getent group docker | cut -d: -f3`.

## Stop

```bash
mise run airflow:down
```

## Reset

This deletes local Airflow metadata volume, local Evidence named volumes, plus
`.local/data` and `.local/logs`.

```bash
mise run airflow:reset
```

Mise asks for confirmation before deleting local state.

## Development Loop

1. edit ingestion and dlt code
2. `mise run ingestion:image`
3. run raw backfill through local Airflow
4. run host dbt from `transformation/` against local Compose PostgreSQL
5. run `mise run transform:build` to prepare data permissions and build curated marts into repo-root `.local/data`
6. run `mise run bi:up` to generate Evidence sources and start local BI
7. commit
8. validate in CI and publish GHCR image tags from trusted `master` builds
9. deploy through `homelab-data-platform`

## Notes

- Keep real secrets out of git. Commit only `.env.example`.
- Published datasets for this stack live under `.local/data`, not shared NFS.
- Durable state still means DuckLake data files plus PostgreSQL-backed services;
  container `dlt` runtime state should remain ephemeral.
- The `raw_files` ledger DB/user is created by Postgres init scripts only when the
  `postgres-data` volume is first initialized. If you already started the stack before
  adding it, run `mise run airflow:reset` or create the DB/user manually.
- DuckDB files created by local experiments must stay local or scratch-only.
- The Docker socket mount gives Airflow local control over the host Docker daemon. Keep
  this local-only; do not use this pattern in k3s.
- Production-style Airflow runtime is managed in `homelab-data-platform`.
- Production DAGs should use `KubernetesPodOperator` with immutable GHCR image tags from
  the `Ingestion Image` workflow, not local Docker socket access.
- Future hardening may move containers to read-only root filesystems with explicit
  scratch mounts.
