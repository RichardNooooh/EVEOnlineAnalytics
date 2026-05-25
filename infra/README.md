# infra/

This directory is now limited to local Airflow and published-data harness in
`infra/local/`.

Use the repo-root `make local-airflow-*` and `make local-bi-*` targets with
`infra/local/` for local analytics runtime. Compose-run Evidence app lives in
repo-root `bi/`.

Reusable platform infrastructure, cluster bootstrap, and production-style
deployment live in `homelab-data-platform`.
