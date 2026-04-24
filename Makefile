# Local development entrypoints.

LOCAL_AIRFLOW_ENV := infra/local/.env
LOCAL_AIRFLOW_VERSIONS := infra/local/versions.txt
LOCAL_COMPOSE := docker compose --env-file $(LOCAL_AIRFLOW_ENV) --env-file $(LOCAL_AIRFLOW_VERSIONS) -f infra/local/compose.yml

.DEFAULT_GOAL := help

.PHONY: help local-airflow-env local-airflow-up local-airflow-down local-airflow-reset local-pipeline-smoke

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

local-airflow-env:
	@test -f $(LOCAL_AIRFLOW_ENV) || { echo "ERROR: missing $(LOCAL_AIRFLOW_ENV). Copy infra/local/.env.example first."; exit 1; }
	@test -f $(LOCAL_AIRFLOW_VERSIONS) || { echo "ERROR: missing $(LOCAL_AIRFLOW_VERSIONS)."; exit 1; }

local-airflow-up: local-airflow-env ## Start local Airflow + Postgres demo stack
	@mkdir -p .local/data .local/logs
	$(LOCAL_COMPOSE) up --build -d postgres airflow-init airflow-api-server airflow-scheduler airflow-dag-processor

local-airflow-down: local-airflow-env ## Stop local Airflow demo stack
	$(LOCAL_COMPOSE) down --remove-orphans

local-airflow-reset: local-airflow-env ## Delete local Airflow stack state (requires CONFIRM=yes)
ifneq ($(CONFIRM),yes)
	@echo "ERROR: Refusing to delete local Airflow state. Re-run with CONFIRM=yes"
	@exit 1
endif
	$(LOCAL_COMPOSE) down --volumes --remove-orphans
	rm -rf .local/data .local/logs

local-pipeline-smoke: local-airflow-env ## Smoke check local Airflow, dlt, dbt, DuckDB, and mounts
	@mkdir -p .local/data .local/logs
	$(LOCAL_COMPOSE) run --rm airflow-cli airflow db check
	$(LOCAL_COMPOSE) run --rm airflow-cli python -c "import dlt, duckdb, pyarrow, pandas, dbt.version; from pathlib import Path; roots=[Path('/opt/airflow/dags'), Path('/opt/eve-market/ingestion'), Path('/opt/eve-market/transform'), Path('/opt/eve-market/datasets'), Path('/opt/eve-market/data')]; missing=[str(p) for p in roots if not p.exists()]; assert not missing, missing; print('local Airflow+dlt smoke ok')"
