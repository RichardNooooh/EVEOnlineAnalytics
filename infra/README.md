# infra/

This directory is now limited to local Airflow and published-data harness in
`infra/local/`.

Use the repo-root `make local-airflow-*` targets and `infra/local/` for local
analytics data publication. Host-run Evidence app now lives in repo-root
`bi/`.

Reusable platform infrastructure, cluster bootstrap, and production-style
deployment live in `homelab-data-platform`.
