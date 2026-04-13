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
TOFU          := tofu
HELM          := helm
KUBECTL       := kubectl

# Configuration
EXPECTED_KUBE_CONTEXT := eve-market
AIRFLOW_NAMESPACE     := airflow
ML_NAMESPACE          := ml
MONITORING_NAMESPACE  := monitoring
K3S_TOKEN_FILE        := $(ANSIBLE_DIR)/inventory/k3s_cluster.key
LEGACY_K3S_TOKEN_FILE := $(ANSIBLE_DIR)/inventory/k3s-token.txt
GRAFANA_ADMIN_ENV_FILE := .grafana-admin.env

# =============================================================================
# Default Target
# =============================================================================

.DEFAULT_GOAL := help

# =============================================================================
# Help / Meta
# =============================================================================

.PHONY: help check-deps status

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check-deps: ## Verify tofu, ansible-playbook, helm, kubectl are installed
	@for bin in $(TOFU) ansible-playbook $(HELM) $(KUBECTL); do \
	  command -v $$bin >/dev/null || { echo "ERROR: missing: $$bin"; exit 1; }; done
	@echo "All dependencies present"

status: ## Full view: VMs, k3s nodes, pods per namespace (no truncation)
	@echo "=== Proxmox VMs ==="
	@vms="$$($(TOFU) -chdir=$(PROXMOX_DIR) state list 2>/dev/null | grep '^proxmox_virtual_environment_vm\.k3s')"; \
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

.PHONY: tf-init tf-fmt tf-validate vms-plan vms vms-destroy

tf-init: ## Initialize OpenTofu in Proxmox directory
	$(TOFU) -chdir=$(PROXMOX_DIR) init

tf-fmt: ## Format all OpenTofu files recursively
	$(TOFU) -chdir=$(PROXMOX_DIR) fmt -recursive

tf-validate: tf-init ## Validate OpenTofu configuration
	$(TOFU) -chdir=$(PROXMOX_DIR) validate

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
	$(TOFU) -chdir=$(PROXMOX_DIR) destroy -target proxmox_virtual_environment_vm.k3s

# =============================================================================
# Configure (Ansible)
# =============================================================================

.PHONY: ping preflight cluster cluster-init cluster-reboot snapshot kubeconfig nfs ssh ansible-lint

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

ssh: ## SSH to a node: make ssh NODE=k3s-01
ifndef NODE
	@echo "ERROR: NODE variable required. Usage: make ssh NODE=k3s-01"
	@exit 1
endif
	@cd $(ANSIBLE_DIR) && ansible -i inventory/hosts.ini -m debug -a "var=hostvars['$(NODE)']" $(NODE) 2>/dev/null | grep -oE 'ansible_host.*' | head -1 | sed 's/.*"\([^"]*\)".*/\1/' | xargs -I {} ssh {}

ansible-lint: ## Run ansible-lint on all Ansible files
	ansible-lint $(ANSIBLE_DIR)/

# =============================================================================
# Deploy (kubectl + Helm)
# =============================================================================

.PHONY: _helm-repos helm-lint helm-render k8s-base apply-monitoring-secrets deploy-all deploy-airflow deploy-mlflow deploy-monitoring plan-helm uninstall-services

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

k8s-base: kube-context ## Apply base k8s manifests (namespaces, storage)
	$(KUBECTL) apply -f $(K8S_DIR)/namespaces.yml
	$(KUBECTL) apply -f $(K8S_DIR)/nfs-pv.yml

apply-monitoring-secrets: ## Apply generated monitoring secrets from local env files
	@test -f $(GRAFANA_ADMIN_ENV_FILE) || { echo "ERROR: missing $(GRAFANA_ADMIN_ENV_FILE). Run 'make vms' or 'cd $(PROXMOX_DIR) && $(TOFU) apply' first."; exit 1; }
	$(KUBECTL) create secret generic grafana-admin-credentials \
	    --namespace $(MONITORING_NAMESPACE) \
	    --from-env-file=$(GRAFANA_ADMIN_ENV_FILE) \
	    --dry-run=client -o yaml | $(KUBECTL) apply -f -

deploy-all: kube-context _helm-repos k8s-base ## Deploy all services (full chain)
	@$(MAKE) deploy-airflow
	@$(MAKE) deploy-mlflow
	@$(MAKE) deploy-monitoring

deploy-airflow: kube-context _helm-repos ## Deploy Airflow Helm chart
	$(HELM) upgrade --install airflow apache-airflow/airflow \
	    --values $(HELM_DIR)/airflow.yml \
	    --namespace $(AIRFLOW_NAMESPACE) --create-namespace

deploy-mlflow: kube-context _helm-repos ## Deploy MLflow Helm chart
	$(HELM) upgrade --install mlflow community-charts/mlflow \
	    --values $(HELM_DIR)/mlflow.yml \
	    --namespace $(ML_NAMESPACE) --create-namespace

deploy-monitoring: kube-context _helm-repos k8s-base apply-monitoring-secrets ## Deploy VictoriaMetrics + Grafana
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

bootstrap: check-deps vms cluster nfs deploy-all ## Full bootstrap: VMs → cluster → NFS → deploy-all
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

backup-state: ## Backup OpenTofu state + k3s token + kubeconfig to archive
	@echo "Creating backup archive..."
	@mkdir -p backup-$$(date +%Y%m%d-%H%M%S)
	@cp -r $(PROXMOX_DIR)/*.tfstate* backup-$$(date +%Y%m%d-%H%M%S)/ 2>/dev/null || true
	@cp $(K3S_TOKEN_FILE) backup-$$(date +%Y%m%d-%H%M%S)/ 2>/dev/null || true
	@cp ~/.kube/config backup-$$(date +%Y%m%d-%H%M%S)/kubeconfig 2>/dev/null || true
	@echo "Backup created in backup-$$(date +%Y%m%d-%H%M%S)/"

# =============================================================================
# Cleanup
# =============================================================================

.PHONY: clean clean-state clean-secrets

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

clean-secrets: ## Delete k3s token files and local kubeconfig backups (requires CONFIRM=yes)
ifneq ($(CONFIRM),yes)
	@echo "ERROR: Refusing to delete secrets. Re-run with CONFIRM=yes"
	@exit 1
endif
	rm -f $(K3S_TOKEN_FILE) $(LEGACY_K3S_TOKEN_FILE)
	rm -f backup-*/k3s_cluster.key 2>/dev/null || true
	rm -f backup-*/kubeconfig 2>/dev/null || true
	@echo "Secrets cleaned"
