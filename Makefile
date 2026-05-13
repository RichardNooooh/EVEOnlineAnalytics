# Local development entrypoints.

LOCAL_AIRFLOW_ENV := infra/local/.env
LOCAL_AIRFLOW_VERSIONS := infra/local/versions.txt
LOCAL_COMPOSE := docker compose --env-file $(LOCAL_AIRFLOW_ENV) --env-file $(LOCAL_AIRFLOW_VERSIONS) -f infra/local/compose.yml
INGESTION_IMAGE ?= eve-market-ingestion:local

.DEFAULT_GOAL := help

.PHONY: help python-format python-format-check ingestion-image ingestion-image-smoke local-airflow-env local-airflow-up local-airflow-down local-airflow-reset local-pipeline-smoke local-airflow-docker-smoke

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

python-format: ## Format Python files with Ruff
	ruff format .

python-format-check: ## Check Python formatting with Ruff
	ruff format --check .

ingestion-image: ## Build ingestion job image
	docker build -f ingestion/Dockerfile -t $(INGESTION_IMAGE) ingestion

ingestion-image-smoke: ingestion-image ## Smoke check ingestion job image entrypoint
	docker run --rm $(INGESTION_IMAGE) --help

local-airflow-env:
	@test -f $(LOCAL_AIRFLOW_ENV) || { echo "ERROR: missing $(LOCAL_AIRFLOW_ENV). Copy infra/local/.env.example first."; exit 1; }
	@test -f $(LOCAL_AIRFLOW_VERSIONS) || { echo "ERROR: missing $(LOCAL_AIRFLOW_VERSIONS)."; exit 1; }

local-airflow-up: local-airflow-env ## Start local Airflow + Postgres demo stack
	@mkdir -p .local/data .local/logs
	$(LOCAL_COMPOSE) up --build -d

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
	$(LOCAL_COMPOSE) run --rm airflow-cli python -c "import dlt, duckdb, pyarrow, pandas, psycopg, dbt.version; from pathlib import Path; roots=[Path('/opt/airflow/dags'), Path('/opt/eve-market/ingestion'), Path('/opt/eve-market/transform'), Path('/opt/eve-market/datasets'), Path('/opt/eve-market/data')]; missing=[str(p) for p in roots if not p.exists()]; assert not missing, missing; print('local Airflow+dlt smoke ok')"

local-airflow-docker-smoke: local-airflow-env ingestion-image ## Smoke check Airflow DockerOperator support
	$(LOCAL_COMPOSE) run --rm airflow-cli python -c "from airflow.providers.docker.operators.docker import DockerOperator; import docker; assert docker.from_env().ping(); print('local Airflow DockerOperator smoke ok')"
