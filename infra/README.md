# infra/

This directory is now limited to local Airflow and published-data harness in
`infra/local/`.

Use the repo-root `mise run airflow:up`, `mise run airflow:down`,
`mise run airflow:reset`, `mise run bi:up`, and `mise run bi:down` tasks with
`infra/local/` for local analytics runtime. Compose-run Evidence app lives in
repo-root `bi/`.

Reusable platform infrastructure, cluster bootstrap, and production-style
deployment live in `homelab-data-platform`.
