# EVE Online Market Analysis

> Note
> Some infrastructure and operational hardening is intentionally deferred until the
> main project build is complete. This includes current PostgreSQL follow-up work
> and similar finer details across other components, such as security,
> backup/recovery, and related production-polish concerns.

## Local Airflow + dlt Runtime

Local Compose stack provides fast ingestion iteration and portfolio demo access without
requiring Proxmox, k3s, TrueNAS, or Helm. It runs Airflow with a local Postgres
metadata database, bind-mounted DAGs and project code, and local dataset storage under
`.local/data`.

This runtime is a development harness, not production. It does not replace the
canonical k3s + Helm architecture documented in `docs/architecture.md`.

Production mapping:

- `.local/data` approximates TrueNAS NFS dataset storage
- local Postgres approximates the Airflow metadata database
- bind-mounted DAGs and code approximate the deployed Airflow image or sync mechanism

Basic commands:

```bash
make local-airflow-up
make local-airflow-down
make local-airflow-reset
make local-pipeline-smoke
```

Expected development loop:

1. edit ingestion and dlt code
2. run locally
3. validate through local Airflow
4. commit
5. build and test in CI
6. deploy to k3s

See `infra/local/README.md` for local runtime details.
