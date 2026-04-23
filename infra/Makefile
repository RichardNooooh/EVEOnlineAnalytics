# Infrastructure Automation Makefile
# Proxmox Infrastructure Management — Single entrypoint for IaC workflows
# =============================================================================
# Variables
# =============================================================================

# Directories
PROXMOX_DIR   := terraform/proxmox
ANSIBLE_DIR   := ansible
HELM_DIR      := helm
K8S_DIR       := k8s

# Tools
ANSIBLE       := ansible-playbook
ANSIBLE_LINT  := ansible-lint
TOFU          := tofu
HELM          := helm
KUBECTL       := kubectl
YAMLLINT      := yamllint
PRE_COMMIT    := pre-commit

# Configuration
EXPECTED_KUBE_CONTEXT := eve-market
AIRFLOW_NAMESPACE     := airflow
ML_NAMESPACE          := ml
MONITORING_NAMESPACE  := monitoring
K3S_TOKEN_FILE        := $(ANSIBLE_DIR)/inventory/k3s_cluster.key
GRAFANA_ADMIN_ENV_FILE := $(K8S_DIR)/.grafana-admin.env
AIRFLOW_APP_ENV_FILE  := $(K8S_DIR)/.airflow-app.env
AIRFLOW_DB_ENV_FILE   := $(K8S_DIR)/.airflow-db.env
ML_APP_ENV_FILE       := $(K8S_DIR)/.ml-app.env
ML_DB_ENV_FILE        := $(K8S_DIR)/.ml-db.env
MONITORING_APP_ENV_FILE := $(K8S_DIR)/.monitoring-app.env
AIRFLOW_APP_ENV_EXAMPLE_FILE := $(K8S_DIR)/.airflow-app.env.example
ML_APP_ENV_EXAMPLE_FILE := $(K8S_DIR)/.ml-app.env.example
MONITORING_APP_ENV_EXAMPLE_FILE := $(K8S_DIR)/.monitoring-app.env.example
POSTGRESQL_HOST_VARS_DIR := $(ANSIBLE_DIR)/inventory/host_vars
GRAFANA_ADMIN_SECRET_NAME := grafana-admin-credentials
AIRFLOW_APP_SECRET_NAME := airflow-app-secrets
ML_APP_SECRET_NAME    := ml-app-secrets
MONITORING_APP_SECRET_NAME := monitoring-app-secrets

# =============================================================================
# Default Target
# =============================================================================

.DEFAULT_GOAL := help

# =============================================================================
# Help / Meta
# =============================================================================

.PHONY: help check-deps status

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check-deps: ## Verify core infra tooling is installed
	@for bin in $(TOFU) $(ANSIBLE) $(ANSIBLE_LINT) $(YAMLLINT) $(HELM) $(KUBECTL) $(PRE_COMMIT); do \
	  command -v $$bin >/dev/null || { echo "ERROR: missing: $$bin"; exit 1; }; done
	@echo "All dependencies present"

status: ## Full view: VMs, k3s nodes, pods per namespace (no truncation)
	@echo "=== Proxmox VMs ==="
	@vms="$$($(TOFU) -chdir=$(PROXMOX_DIR) state list 2>/dev/null | grep '^proxmox_virtual_environment_vm\.')"; \
	if [ -z "$$vms" ]; then \
	  echo "No VMs deployed yet"; \
	else \
	  for vm in $$vms; do \
	    $(TOFU) -chdir=$(PROXMOX_DIR) state show "$$vm" | \
	      awk '/^    name[[:space:]]+= / { name=$$3 } /^    vm_id[[:space:]]+= / { vm_id=$$3 } /^    node_name[[:space:]]+= / { node=$$3 } /^    started[[:space:]]+= / { started=$$3 } END { gsub(/"/, "", name); gsub(/"/, "", node); printf "%s (vm_id=%s, node=%s, started=%s)\n", name, vm_id, node, started }'; \
	  done; \
	fi
	@echo ""
	@echo "=== k8s Nodes ==="
	@$(KUBECTL) get nodes 2>/dev/null || echo "k3s cluster not accessible"
	@echo ""
	@echo "=== Service Status ==="
	@$(KUBECTL) get pods --all-namespaces 2>/dev/null || echo "Services not deployed"

# =============================================================================
# Guard Targets
# =============================================================================

.PHONY: kube-context

# TODO: configure kube contexts to make things cleaner
kube-context: ## Assert current kubectl context matches expected
	# @[ "$$($(KUBECTL) config current-context 2>/dev/null)" = "$(EXPECTED_KUBE_CONTEXT)" ] \
	#   || { echo "ERROR: wrong kube context. Expected: $(EXPECTED_KUBE_CONTEXT)"; exit 1; }

# =============================================================================
# Provision (OpenTofu)
# =============================================================================

.PHONY: tf-init tf-fmt tf-fmt-check tf-init-check tf-validate tf-lint vms-plan vms vms-destroy

tf-init: ## Initialize OpenTofu in Proxmox directory
	$(TOFU) -chdir=$(PROXMOX_DIR) init

tf-fmt: ## Format all OpenTofu files recursively
	$(TOFU) -chdir=$(PROXMOX_DIR) fmt -recursive

tf-fmt-check: ## Check OpenTofu formatting recursively
	$(TOFU) -chdir=$(PROXMOX_DIR) fmt -check -recursive

tf-init-check: ## Initialize OpenTofu providers without backend access
	$(TOFU) -chdir=$(PROXMOX_DIR) init -backend=false

tf-validate: tf-init-check ## Validate OpenTofu configuration
	$(TOFU) -chdir=$(PROXMOX_DIR) validate

tf-lint: tf-fmt-check tf-validate ## Run OpenTofu formatting and validation checks

vms-plan: tf-init ## Plan infrastructure changes in Proxmox
	$(TOFU) -chdir=$(PROXMOX_DIR) plan

vms: tf-init ## Apply VMs
	$(TOFU) -chdir=$(PROXMOX_DIR) apply
	@echo ""
	@echo "VMs created. Next step: make cluster"

vms-destroy: ## Destroy Proxmox VMs (requires CONFIRM=yes)
ifneq ($(CONFIRM),yes)
	@echo "ERROR: Refusing to destroy VMs. Re-run with CONFIRM=yes"
	@exit 1
endif
	$(TOFU) -chdir=$(PROXMOX_DIR) destroy -target proxmox_virtual_environment_vm.k3s -target proxmox_virtual_environment_vm.postgresql

# =============================================================================
# Configure (Ansible)
# =============================================================================

.PHONY: ping preflight cluster cluster-init cluster-reboot snapshot kubeconfig nfs postgresql ssh yaml-lint-ansible yaml-lint-k8s ansible-syntax-check ansible-lint

ping: ## Ping all k3s servers to verify connectivity
	cd $(ANSIBLE_DIR) && ansible -m ping k3s_servers

preflight: ## Run Ansible preflight checks only
	cd $(ANSIBLE_DIR) && $(ANSIBLE) playbooks/preflight.yml

cluster: ## Run full site.yml playbook (preflight → common → k3s → nfs → verify)
	cd $(ANSIBLE_DIR) && $(ANSIBLE) site.yml

cluster-init: ## Run k3s-init.yml directly (low-level escape hatch)
	cd $(ANSIBLE_DIR) && $(ANSIBLE) playbooks/k3s-init.yml

cluster-reboot: ## Rolling reboot of all k3s nodes
	cd $(ANSIBLE_DIR) && $(ANSIBLE) playbooks/reboot.yml

snapshot: ## Create on-demand etcd snapshot
	cd $(ANSIBLE_DIR) && $(ANSIBLE) playbooks/k3s-etcd-snapshot.yml

kubeconfig: ## Refresh ~/.kube/config from k3s server
	cd $(ANSIBLE_DIR) && $(ANSIBLE) playbooks/kubeconfig-refresh.yml

nfs: ## Configure NFS client on all nodes
	cd $(ANSIBLE_DIR) && $(ANSIBLE) playbooks/nfs-client.yml

postgresql: ## Configure the external PostgreSQL VM
	cd $(ANSIBLE_DIR) && $(ANSIBLE) playbooks/postgresql.yml

ssh: ## SSH to a node: make ssh NODE=k3s-01
ifndef NODE
	@echo "ERROR: NODE variable required. Usage: make ssh NODE=k3s-01"
	@exit 1
endif
	@cd $(ANSIBLE_DIR) && ansible -i inventory/hosts.ini -m debug -a "var=hostvars['$(NODE)']" $(NODE) 2>/dev/null | grep -oE 'ansible_host.*' | head -1 | sed 's/.*"\([^"]*\)".*/\1/' | xargs -I {} ssh {}

yaml-lint-ansible: ## Lint Ansible YAML files
	$(YAMLLINT) -c .yamllint.yml $(ANSIBLE_DIR)

yaml-lint-k8s: ## Lint Kubernetes manifest YAML files
	$(YAMLLINT) -c .yamllint.yml $(K8S_DIR)

ansible-syntax-check: ## Run syntax checks for all Ansible playbooks
	@tmp_inventory=$$(mktemp); trap 'rm -f "$$tmp_inventory"' EXIT; \
	printf '%s\n' '[k3s_servers]' 'localhost ansible_connection=local' '' '[k3s_first_node]' 'localhost' '' '[k3s_other_nodes]' 'localhost' '' '[postgresql]' 'localhost ansible_connection=local' >"$$tmp_inventory"; \
	cd $(ANSIBLE_DIR) && \
	for playbook in site.yml bootstrap.yml playbooks/*.yml; do \
	  $(ANSIBLE) -i "$$tmp_inventory" --syntax-check "$$playbook" || exit 1; \
	done

ansible-lint: ansible-syntax-check yaml-lint-ansible ## Run Ansible syntax, YAML, and lint checks
	cd $(ANSIBLE_DIR) && $(ANSIBLE_LINT) site.yml bootstrap.yml playbooks roles

# =============================================================================
# Deploy (kubectl + Helm)
# =============================================================================

.PHONY: _helm-repos helm-lint helm-render validate-k8s validate-monitoring validate k8s-base apply-generated-secrets apply-manual-secrets apply-secrets apply-airflow-secrets apply-ml-secrets apply-monitoring-app-secrets apply-monitoring-secrets deploy-all deploy-airflow deploy-mlflow deploy-monitoring plan-helm uninstall-services

_helm-repos: ## Add + update Helm repos (internal use)
	$(HELM) repo add apache-airflow https://airflow.apache.org 3>/dev/null || true
	$(HELM) repo add community-charts https://community-charts.github.io/helm-charts 2>/dev/null || true
	$(HELM) repo add vm https://victoriametrics.github.io/helm-charts 2>/dev/null || true
	$(HELM) repo add grafana-community https://grafana-community.github.io/helm-charts 2>/dev/null || true
	$(HELM) repo update

helm-lint: _helm-repos ## Lint Helm charts with their values files
	@if [ -f $(HELM_DIR)/airflow.yml ]; then tmp_dir=$$(mktemp -d); trap 'rm -rf "$$tmp_dir"' EXIT; $(HELM) pull apache-airflow/airflow --untar --untardir "$$tmp_dir" >/dev/null 2>&1; $(HELM) lint "$$tmp_dir"/airflow --values $(HELM_DIR)/airflow.yml; fi
	@if [ -f $(HELM_DIR)/mlflow.yml ]; then tmp_dir=$$(mktemp -d); trap 'rm -rf "$$tmp_dir"' EXIT; $(HELM) pull community-charts/mlflow --untar --untardir "$$tmp_dir" >/dev/null 2>&1; $(HELM) lint "$$tmp_dir"/mlflow --values $(HELM_DIR)/mlflow.yml; fi
	@if [ -f $(HELM_DIR)/victoriametrics.yml ]; then tmp_dir=$$(mktemp -d); trap 'rm -rf "$$tmp_dir"' EXIT; $(HELM) pull vm/victoria-metrics-single --untar --untardir "$$tmp_dir" >/dev/null 2>&1; $(HELM) lint "$$tmp_dir"/victoria-metrics-single --values $(HELM_DIR)/victoriametrics.yml; fi
	@if [ -f $(HELM_DIR)/grafana.yml ]; then tmp_dir=$$(mktemp -d); trap 'rm -rf "$$tmp_dir"' EXIT; $(HELM) pull grafana-community/grafana --untar --untardir "$$tmp_dir" >/dev/null 2>&1; $(HELM) lint "$$tmp_dir"/grafana --values $(HELM_DIR)/grafana.yml; fi

helm-render: _helm-repos ## Render Helm charts with available values files
	@test ! -f $(HELM_DIR)/airflow.yml || $(HELM) template airflow apache-airflow/airflow --values $(HELM_DIR)/airflow.yml --namespace $(AIRFLOW_NAMESPACE) >/dev/null
	@test ! -f $(HELM_DIR)/mlflow.yml || $(HELM) template mlflow community-charts/mlflow --values $(HELM_DIR)/mlflow.yml --namespace $(ML_NAMESPACE) >/dev/null
	@test ! -f $(HELM_DIR)/victoriametrics.yml || $(HELM) template victoriametrics vm/victoria-metrics-single --values $(HELM_DIR)/victoriametrics.yml --namespace $(MONITORING_NAMESPACE) >/dev/null
	@test ! -f $(HELM_DIR)/grafana.yml || $(HELM) template grafana grafana-community/grafana --values $(HELM_DIR)/grafana.yml --namespace $(MONITORING_NAMESPACE) >/dev/null

validate-k8s: ## Validate raw k8s manifests with kubectl client dry-run
	$(KUBECTL) apply --dry-run=client -f $(K8S_DIR)/namespaces.yml >/dev/null
	$(KUBECTL) apply --dry-run=client -f $(K8S_DIR)/nfs-pv.yml >/dev/null

validate-monitoring: _helm-repos ## Render monitoring charts and verify wiring
	@vm_render=$$(mktemp); grafana_render=$$(mktemp); trap 'rm -f "$$vm_render" "$$grafana_render"' EXIT; \
	$(HELM) template victoriametrics vm/victoria-metrics-single --values $(HELM_DIR)/victoriametrics.yml --namespace $(MONITORING_NAMESPACE) >"$$vm_render"; \
	$(HELM) template grafana grafana-community/grafana --values $(HELM_DIR)/grafana.yml --namespace $(MONITORING_NAMESPACE) >"$$grafana_render"; \
	rg -q 'name: victoriametrics-victoria-metrics-single-server' "$$vm_render" || { echo "ERROR: VictoriaMetrics service name mismatch"; exit 1; }; \
	rg -q 'namespace: monitoring' "$$vm_render" || { echo "ERROR: VictoriaMetrics namespace mismatch"; exit 1; }; \
	rg -q 'port: 8428' "$$vm_render" || { echo "ERROR: VictoriaMetrics port 8428 missing"; exit 1; }; \
	rg -q 'http://victoriametrics-victoria-metrics-single-server\.monitoring\.svc\.cluster\.local:8428' "$$grafana_render" || { echo "ERROR: Grafana datasource URL mismatch"; exit 1; }

validate: ansible-lint tf-lint helm-lint helm-render validate-k8s validate-monitoring ## Run infrastructure validation checks

k8s-base: kube-context ## Apply base k8s manifests (namespaces, storage)
	$(KUBECTL) apply -f $(K8S_DIR)/namespaces.yml
	$(KUBECTL) apply -f $(K8S_DIR)/nfs-pv.yml

apply-generated-secrets: apply-monitoring-secrets ## Apply Terraform-generated secrets

apply-manual-secrets: apply-airflow-secrets apply-ml-secrets apply-monitoring-app-secrets ## Apply manual env-backed app secrets

apply-secrets: kube-context k8s-base apply-generated-secrets apply-manual-secrets ## Apply all generated and manual secrets

apply-airflow-secrets: ## Apply Airflow secrets when DB and app inputs are complete
	@if [ ! -f $(AIRFLOW_DB_ENV_FILE) ] && [ ! -f $(AIRFLOW_APP_ENV_FILE) ]; then \
	  echo "Skipping $(AIRFLOW_APP_SECRET_NAME): missing $(AIRFLOW_DB_ENV_FILE) and $(AIRFLOW_APP_ENV_FILE)."; \
	elif [ ! -f $(AIRFLOW_APP_ENV_FILE) ]; then \
	  echo "ERROR: missing $(AIRFLOW_APP_ENV_FILE). Airflow also requires fernet-key and api-secret-key."; \
	  exit 1; \
	elif [ ! -f $(AIRFLOW_DB_ENV_FILE) ] && ! rg -q '^connection=' $(AIRFLOW_APP_ENV_FILE); then \
	  echo "ERROR: missing $(AIRFLOW_DB_ENV_FILE) and no connection= entry found in $(AIRFLOW_APP_ENV_FILE)."; \
	  exit 1; \
	else \
	  set -- $(KUBECTL) create secret generic $(AIRFLOW_APP_SECRET_NAME) --namespace $(AIRFLOW_NAMESPACE); \
	  if [ -f $(AIRFLOW_DB_ENV_FILE) ]; then \
	    set -- "$$@" --from-env-file=$(AIRFLOW_DB_ENV_FILE); \
	  else \
	    echo "Note: using connection= from $(AIRFLOW_APP_ENV_FILE) for $(AIRFLOW_APP_SECRET_NAME)."; \
	  fi; \
	  set -- "$$@" --from-env-file=$(AIRFLOW_APP_ENV_FILE); \
	  "$$@" --dry-run=client -o yaml | $(KUBECTL) apply -f -; \
	fi

apply-ml-secrets: ## Apply merged ML DB and app secrets
	@if [ ! -f $(ML_DB_ENV_FILE) ] && [ ! -f $(ML_APP_ENV_FILE) ]; then \
	  echo "Skipping $(ML_APP_SECRET_NAME): missing $(ML_DB_ENV_FILE) and $(ML_APP_ENV_FILE)."; \
	else \
	  set -- $(KUBECTL) create secret generic $(ML_APP_SECRET_NAME) --namespace $(ML_NAMESPACE); \
	  if [ -f $(ML_DB_ENV_FILE) ]; then \
	    set -- "$$@" --from-env-file=$(ML_DB_ENV_FILE); \
	  fi; \
	  if [ -f $(ML_APP_ENV_FILE) ]; then \
	    set -- "$$@" --from-env-file=$(ML_APP_ENV_FILE); \
	  else \
	    echo "Note: $(ML_APP_ENV_FILE) not present; applying only generated database keys for $(ML_APP_SECRET_NAME)."; \
	  fi; \
	  "$$@" --dry-run=client -o yaml | $(KUBECTL) apply -f -; \
	fi

apply-monitoring-app-secrets: ## Apply manual monitoring app secrets from local env file
	@if [ ! -f $(MONITORING_APP_ENV_FILE) ]; then \
	  echo "Skipping $(MONITORING_APP_SECRET_NAME): missing $(MONITORING_APP_ENV_FILE). Copy $(MONITORING_APP_ENV_EXAMPLE_FILE) to $(MONITORING_APP_ENV_FILE) to define monitoring app secrets."; \
	else \
	  $(KUBECTL) create secret generic $(MONITORING_APP_SECRET_NAME) \
	      --namespace $(MONITORING_NAMESPACE) \
	      --from-env-file=$(MONITORING_APP_ENV_FILE) \
	      --dry-run=client -o yaml | $(KUBECTL) apply -f -; \
	fi

apply-monitoring-secrets: ## Apply generated monitoring secrets from Terraform output
	@test -f $(GRAFANA_ADMIN_ENV_FILE) || { echo "ERROR: missing $(GRAFANA_ADMIN_ENV_FILE). Run 'make vms' or 'cd $(PROXMOX_DIR) && $(TOFU) apply' first."; exit 1; }
	$(KUBECTL) create secret generic $(GRAFANA_ADMIN_SECRET_NAME) \
	    --namespace $(MONITORING_NAMESPACE) \
	    --from-env-file=$(GRAFANA_ADMIN_ENV_FILE) \
	    --dry-run=client -o yaml | $(KUBECTL) apply -f -

deploy-all: kube-context _helm-repos k8s-base ## Deploy all checked-in ready services
	@$(MAKE) deploy-airflow
	@$(MAKE) deploy-mlflow
	@$(MAKE) deploy-monitoring

deploy-airflow: kube-context _helm-repos k8s-base apply-airflow-secrets ## Deploy Airflow Helm chart
	@test -f $(HELM_DIR)/airflow.yml || { echo "ERROR: missing $(HELM_DIR)/airflow.yml"; exit 1; }
	$(HELM) upgrade --install airflow apache-airflow/airflow \
	    --values $(HELM_DIR)/airflow.yml \
	    --namespace $(AIRFLOW_NAMESPACE) --create-namespace

deploy-mlflow: kube-context _helm-repos k8s-base ## Deploy MLflow Helm chart when values are checked in
	@if [ ! -f $(HELM_DIR)/mlflow.yml ]; then \
	  echo "Skipping mlflow: missing $(HELM_DIR)/mlflow.yml."; \
	else \
	  $(MAKE) apply-ml-secrets && \
	  $(HELM) upgrade --install mlflow community-charts/mlflow \
	      --values $(HELM_DIR)/mlflow.yml \
	      --namespace $(ML_NAMESPACE) --create-namespace; \
	fi

deploy-monitoring: kube-context _helm-repos k8s-base apply-monitoring-secrets apply-monitoring-app-secrets ## Deploy VictoriaMetrics + Grafana
	$(HELM) upgrade --install victoriametrics vm/victoria-metrics-single \
	    --values $(HELM_DIR)/victoriametrics.yml \
	    --namespace $(MONITORING_NAMESPACE) --create-namespace
	$(HELM) upgrade --install grafana grafana-community/grafana \
	    --values $(HELM_DIR)/grafana.yml \
	    --namespace $(MONITORING_NAMESPACE) --create-namespace

plan-helm: kube-context _helm-repos ## Run helm diff upgrade on all charts (drift check)
	@echo "Checking helm diff for all charts..."
	@$(HELM) diff upgrade airflow apache-airflow/airflow --values $(HELM_DIR)/airflow.yml --namespace $(AIRFLOW_NAMESPACE) 2>/dev/null || echo "airflow: no diff or not installed"
	@$(HELM) diff upgrade mlflow community-charts/mlflow --values $(HELM_DIR)/mlflow.yml --namespace $(ML_NAMESPACE) 2>/dev/null || echo "mlflow: no diff or not installed"
	@$(HELM) diff upgrade victoriametrics vm/victoria-metrics-single --values $(HELM_DIR)/victoriametrics.yml --namespace $(MONITORING_NAMESPACE) 2>/dev/null || echo "victoriametrics: no diff or not installed"
	@$(HELM) diff upgrade grafana grafana-community/grafana --values $(HELM_DIR)/grafana.yml --namespace $(MONITORING_NAMESPACE) 2>/dev/null || echo "grafana: no diff or not installed"

uninstall-services: kube-context ## Uninstall all Helm releases (requires CONFIRM=yes)
ifneq ($(CONFIRM),yes)
	@echo "ERROR: Refusing to uninstall. Re-run with CONFIRM=yes"
	@exit 1
endif
	$(HELM) uninstall airflow --namespace $(AIRFLOW_NAMESPACE) 2>/dev/null || true
	$(HELM) uninstall mlflow --namespace $(ML_NAMESPACE) 2>/dev/null || true
	$(HELM) uninstall victoriametrics --namespace $(MONITORING_NAMESPACE) 2>/dev/null || true
	$(HELM) uninstall grafana --namespace $(MONITORING_NAMESPACE) 2>/dev/null || true

# =============================================================================
# Full-stack Workflows
# =============================================================================

.PHONY: bootstrap teardown backup-state cluster-uninstall

bootstrap: check-deps vms cluster postgresql deploy-all ## Full bootstrap: VMs → cluster → postgresql → deploy-all
	@echo ""
	@echo "Full bootstrap complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Verify: make status"
	@echo "  2. Configure DNS entries for services"
	@echo "  3. Run data ingestion pipelines"
	@echo "  4. Deploy Tableau workbooks"

teardown: ## Full teardown: services → cluster-uninstall → VMs (requires CONFIRM=yes)
ifneq ($(CONFIRM),yes)
	@echo "ERROR: Refusing to teardown. Re-run with CONFIRM=yes"
	@exit 1
endif
	@$(MAKE) uninstall-services CONFIRM=yes
	@$(MAKE) cluster-uninstall CONFIRM=yes
	@$(MAKE) vms-destroy CONFIRM=yes

cluster-uninstall: ## Uninstall k3s from all nodes (requires CONFIRM=yes)
ifneq ($(CONFIRM),yes)
	@echo "ERROR: Refusing to uninstall cluster. Re-run with CONFIRM=yes"
	@exit 1
endif
	cd $(ANSIBLE_DIR) && $(ANSIBLE) playbooks/k3s-uninstall.yml

backup-state: ## Backup OpenTofu state, local secret files, and kubeconfig to archive
	@echo "Creating backup archive..."
	@backup_dir=backup-$$(date +%Y%m%d-%H%M%S); \
	mkdir -p "$$backup_dir"; \
	cp -r $(PROXMOX_DIR)/*.tfstate* "$$backup_dir"/ 2>/dev/null || true; \
	cp $(K3S_TOKEN_FILE) "$$backup_dir"/ 2>/dev/null || true; \
	cp $(POSTGRESQL_HOST_VARS_DIR)/*.yml "$$backup_dir"/ 2>/dev/null || true; \
	cp $(AIRFLOW_DB_ENV_FILE) "$$backup_dir"/ 2>/dev/null || true; \
	cp $(AIRFLOW_APP_ENV_FILE) "$$backup_dir"/ 2>/dev/null || true; \
	cp $(ML_DB_ENV_FILE) "$$backup_dir"/ 2>/dev/null || true; \
	cp $(ML_APP_ENV_FILE) "$$backup_dir"/ 2>/dev/null || true; \
	cp $(MONITORING_APP_ENV_FILE) "$$backup_dir"/ 2>/dev/null || true; \
	cp $(GRAFANA_ADMIN_ENV_FILE) "$$backup_dir"/ 2>/dev/null || true; \
	cp ~/.kube/config "$$backup_dir"/kubeconfig 2>/dev/null || true; \
	echo "Backup created in $$backup_dir/"

# =============================================================================
# Cleanup
# =============================================================================

.PHONY: pre-commit-install pre-commit-run clean clean-state clean-secrets

pre-commit-install: ## Install repository pre-commit hooks
	$(PRE_COMMIT) install

pre-commit-run: ## Run pre-commit hooks across all files
	$(PRE_COMMIT) run --all-files

clean: ## Remove local caches (.terraform, .ansible_cache, *.retry)
ifneq ($(CONFIRM),yes)
	@echo "ERROR: Refusing to clean. Re-run with CONFIRM=yes"
	@exit 1
endif
	rm -rf $(PROXMOX_DIR)/.terraform
	rm -f $(PROXMOX_DIR)/.terraform.lock.hcl
	rm -rf $(ANSIBLE_DIR)/.ansible_cache
	rm -f $(ANSIBLE_DIR)/*.retry
	@echo "Caches cleaned"

clean-state: ## Delete OpenTofu state files (requires CONFIRM=yes)
ifneq ($(CONFIRM),yes)
	@echo "ERROR: Refusing to delete state. Re-run with CONFIRM=yes"
	@exit 1
endif
	rm -f $(PROXMOX_DIR)/terraform.tfstate*
	@echo "OpenTofu state files removed"

clean-secrets: ## Delete local secret files and secret backups (requires CONFIRM=yes)
ifneq ($(CONFIRM),yes)
	@echo "ERROR: Refusing to delete secrets. Re-run with CONFIRM=yes"
	@exit 1
endif
	rm -f $(K3S_TOKEN_FILE) $(POSTGRESQL_HOST_VARS_DIR)/*.yml $(AIRFLOW_DB_ENV_FILE) $(AIRFLOW_APP_ENV_FILE) $(ML_DB_ENV_FILE) $(ML_APP_ENV_FILE) $(MONITORING_APP_ENV_FILE) $(GRAFANA_ADMIN_ENV_FILE)
	rm -f backup-*/*.yml 2>/dev/null || true
	rm -f backup-*/k3s_cluster.key 2>/dev/null || true
	rm -f backup-*/.airflow-db.env 2>/dev/null || true
	rm -f backup-*/.airflow-app.env 2>/dev/null || true
	rm -f backup-*/.ml-db.env 2>/dev/null || true
	rm -f backup-*/.ml-app.env 2>/dev/null || true
	rm -f backup-*/.monitoring-app.env 2>/dev/null || true
	rm -f backup-*/.grafana-admin.env 2>/dev/null || true
	rm -f backup-*/kubeconfig 2>/dev/null || true
	@echo "Secrets cleaned"
