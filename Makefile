# Local development entrypoints.

LOCAL_AIRFLOW_ENV := infra/local/.env
LOCAL_AIRFLOW_VERSIONS := infra/local/versions.txt
LOCAL_COMPOSE := docker compose --env-file $(LOCAL_AIRFLOW_ENV) --env-file $(LOCAL_AIRFLOW_VERSIONS) -f infra/local/compose.yml

ifneq ($(wildcard $(LOCAL_AIRFLOW_ENV)),)
include $(LOCAL_AIRFLOW_ENV)
endif

EVE_MARKET_INGESTION_IMAGE ?= eve-market-ingestion:local
INGESTION_IMAGE ?= $(EVE_MARKET_INGESTION_IMAGE)

.DEFAULT_GOAL := help

.PHONY: help python-format python-format-check python-ty-check sql-format sql-lint ingestion-image ingestion-image-rebuild ingestion-image-smoke local-airflow-env local-airflow-up local-airflow-down local-airflow-reset local-pipeline-smoke local-airflow-docker-smoke local-data-permissions-fix local-bi-up local-bi-down local-bi-smoke local-transform-bi-smoke

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

python-format: ## Format Python files with Ruff
	ruff format .

python-format-check: ## Check Python formatting with Ruff
	ruff format --check .

python-ty-check: ## Check Python types with Ty (ingestion)
	ty check ingestion/

sql-format: ## Format transformation SQL with SQLFluff
	sqlfluff format transformation/

sql-lint: ## Lint transformation SQL with SQLFluff
	sqlfluff lint transformation/

ingestion-image: ## Build ingestion job image
	docker rmi $(INGESTION_IMAGE) 2>/dev/null || true
	docker build -f ingestion/Dockerfile -t $(INGESTION_IMAGE) ingestion

ingestion-image-rebuild: ## Rebuild ingestion job image without cache
	docker rmi $(INGESTION_IMAGE) 2>/dev/null || true
	docker build --pull --no-cache -f ingestion/Dockerfile -t $(INGESTION_IMAGE) ingestion

ingestion-image-smoke: ingestion-image ## Smoke check ingestion job image entrypoint
	docker run --rm $(INGESTION_IMAGE) --help

local-airflow-env:
	@test -f $(LOCAL_AIRFLOW_ENV) || { echo "ERROR: missing $(LOCAL_AIRFLOW_ENV). Copy infra/local/.env.example first."; exit 1; }
	@test -f $(LOCAL_AIRFLOW_VERSIONS) || { echo "ERROR: missing $(LOCAL_AIRFLOW_VERSIONS)."; exit 1; }

local-airflow-up: local-airflow-env ## Start local Airflow + Postgres demo stack
	@mkdir -p .local/data .local/logs
	$(LOCAL_COMPOSE) up -d

local-airflow-down: local-airflow-env ## Stop local Airflow demo stack
	$(LOCAL_COMPOSE) down --remove-orphans

local-airflow-reset: local-airflow-env ## Delete local Airflow stack state (requires CONFIRM=yes)
ifneq ($(CONFIRM),yes)
	@echo "ERROR: Refusing to delete local Airflow state. Re-run with CONFIRM=yes"
	@exit 1
endif
	$(LOCAL_COMPOSE) down --volumes --remove-orphans
	rm -rf .local/data .local/logs

local-pipeline-smoke: local-airflow-env ## Smoke check Airflow DB, DAG parse, and mounts
	@mkdir -p .local/data .local/logs
	$(LOCAL_COMPOSE) run --rm airflow-cli airflow db check
	$(LOCAL_COMPOSE) run --rm airflow-cli python -c "from pathlib import Path; roots=[Path('/opt/airflow/dags'), Path('/opt/eve-market/ingestion'), Path('/opt/eve-market/transform'), Path('/opt/eve-market/datasets'), Path('/opt/eve-market/data')]; missing=[str(p) for p in roots if not p.exists()]; assert not missing, missing; print('local Airflow mount smoke ok')"
	$(LOCAL_COMPOSE) run --rm airflow-cli airflow dags show backfill_market_history > /dev/null

local-airflow-docker-smoke: local-airflow-env ## Smoke check Airflow DockerOperator support
	$(LOCAL_COMPOSE) run --rm airflow-cli python -c "from airflow.providers.docker.operators.docker import DockerOperator; import docker; assert docker.from_env().ping(); print('local Airflow DockerOperator smoke ok')"

local-data-permissions-fix: local-airflow-env ## Make local DuckLake data host-writable for dbt publish
	@mkdir -p .local/data .local/logs
	$(LOCAL_COMPOSE) run --rm --user 0:0 --entrypoint /bin/sh airflow-cli -lc "mkdir -p /opt/eve-market/data/datasets/ducklake/curated && chmod -R a+rwX /opt/eve-market/data"

local-bi-up: local-airflow-env ## Start local Evidence BI container service
	@mkdir -p .local/data .local/logs
	$(MAKE) local-bi-smoke
	$(LOCAL_COMPOSE) --profile bi up -d evidence

local-bi-down: local-airflow-env ## Stop local Evidence BI service
	$(LOCAL_COMPOSE) --profile bi stop evidence

local-bi-smoke: local-airflow-env ## Smoke check local Evidence query in container
	@mkdir -p .local/data .local/logs
	$(LOCAL_COMPOSE) --profile bi run --rm evidence /bin/sh -lc "if [ ! -x node_modules/.bin/evidence ]; then npm ci; fi && npm run sources"

local-transform-bi-smoke: local-data-permissions-fix ## Run host dbt build, then Evidence smoke
	cd transformation && . ./dbt-airflow-local.env.example.sh && uv run dbt build --profiles-dir .
	$(MAKE) local-bi-smoke
