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
	@$(TOFU) -chdir=$(PROXMOX_DIR) output vm_names 2>/dev/null || echo "No VMs deployed yet"
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

kube-context: ## Assert current kubectl context matches expected
	@[ "$$($(KUBECTL) config current-context 2>/dev/null)" = "$(EXPECTED_KUBE_CONTEXT)" ] \
	  || { echo "ERROR: wrong kube context. Expected: $(EXPECTED_KUBE_CONTEXT)"; exit 1; }

# =============================================================================
# Provision (OpenTofu)
# =============================================================================

.PHONY: tf-init tf-fmt tf-validate vms-plan vms vms-yes vms-destroy

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

.PHONY: _helm-repos helm-lint k8s-base deploy-all deploy-airflow deploy-mlflow deploy-monitoring plan-helm uninstall-services

_helm-repos: ## Add + update Helm repos (internal use)
	$(HELM) repo add apache-airflow https://airflow.apache.org 2>/dev/null || true
	$(HELM) repo add community-charts https://community-charts.github.io/helm-charts 2>/dev/null || true
	$(HELM) repo add vm https://victoriametrics.github.io/helm-charts 2>/dev/null || true
	$(HELM) repo add grafana https://grafana.github.io/helm-charts 2>/dev/null || true
	$(HELM) repo update

helm-lint: ## Lint all Helm values files
	$(HELM) lint $(HELM_DIR)/airflow-values.yaml 2>/dev/null || echo "Warning: airflow-values.yaml not found"
	$(HELM) lint $(HELM_DIR)/mlflow-values.yaml 2>/dev/null || echo "Warning: mlflow-values.yaml not found"
	$(HELM) lint $(HELM_DIR)/victoriametrics-values.yaml 2>/dev/null || echo "Warning: victoriametrics-values.yaml not found"
	$(HELM) lint $(HELM_DIR)/grafana-values.yaml 2>/dev/null || echo "Warning: grafana-values.yaml not found"

k8s-base: kube-context ## Apply base k8s manifests (namespaces, storage)
	$(KUBECTL) apply -f $(K8S_DIR)/namespaces.yaml
	$(KUBECTL) apply -f $(K8S_DIR)/nfs-pv.yaml

deploy-all: kube-context _helm-repos k8s-base ## Deploy all services (full chain)
	@$(MAKE) deploy-airflow
	@$(MAKE) deploy-mlflow
	@$(MAKE) deploy-monitoring

deploy-airflow: kube-context _helm-repos ## Deploy Airflow Helm chart
	$(HELM) upgrade --install airflow apache-airflow/airflow \
	    --values $(HELM_DIR)/airflow-values.yaml \
	    --namespace data --create-namespace

deploy-mlflow: kube-context _helm-repos ## Deploy MLflow Helm chart
	$(HELM) upgrade --install mlflow community-charts/mlflow \
	    --values $(HELM_DIR)/mlflow-values.yaml \
	    --namespace ml --create-namespace

deploy-monitoring: kube-context _helm-repos ## Deploy VictoriaMetrics + Grafana
	$(HELM) upgrade --install victoriametrics vm/victoria-metrics-single \
	    --values $(HELM_DIR)/victoriametrics-values.yaml \
	    --namespace monitoring --create-namespace
	$(HELM) upgrade --install grafana grafana/grafana \
	    --values $(HELM_DIR)/grafana-values.yaml \
	    --namespace monitoring --create-namespace

plan-helm: kube-context _helm-repos ## Run helm diff upgrade on all charts (drift check)
	@echo "Checking helm diff for all charts..."
	@$(HELM) diff upgrade airflow apache-airflow/airflow --values $(HELM_DIR)/airflow-values.yaml --namespace data 2>/dev/null || echo "airflow: no diff or not installed"
	@$(HELM) diff upgrade mlflow community-charts/mlflow --values $(HELM_DIR)/mlflow-values.yaml --namespace ml 2>/dev/null || echo "mlflow: no diff or not installed"
	@$(HELM) diff upgrade victoriametrics vm/victoria-metrics-single --values $(HELM_DIR)/victoriametrics-values.yaml --namespace monitoring 2>/dev/null || echo "victoriametrics: no diff or not installed"
	@$(HELM) diff upgrade grafana grafana/grafana --values $(HELM_DIR)/grafana-values.yaml --namespace monitoring 2>/dev/null || echo "grafana: no diff or not installed"

uninstall-services: kube-context ## Uninstall all Helm releases (requires CONFIRM=yes)
ifneq ($(CONFIRM),yes)
	@echo "ERROR: Refusing to uninstall. Re-run with CONFIRM=yes"
	@exit 1
endif
	$(HELM) uninstall airflow --namespace data 2>/dev/null || true
	$(HELM) uninstall mlflow --namespace ml 2>/dev/null || true
	$(HELM) uninstall victoriametrics --namespace monitoring 2>/dev/null || true
	$(HELM) uninstall grafana --namespace monitoring 2>/dev/null || true

# =============================================================================
# Full-stack Workflows
# =============================================================================

.PHONY: bootstrap teardown backup-state cluster-uninstall

bootstrap: check-deps vms-yes cluster nfs deploy-all ## Full bootstrap: VMs → cluster → NFS → deploy-all
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
	@cp $(ANSIBLE_DIR)/inventory/k3s-token.txt backup-$$(date +%Y%m%d-%H%M%S)/ 2>/dev/null || true
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

clean-secrets: ## Delete inventory/k3s-token.txt and local kubeconfig backups (requires CONFIRM=yes)
ifneq ($(CONFIRM),yes)
	@echo "ERROR: Refusing to delete secrets. Re-run with CONFIRM=yes"
	@exit 1
endif
	rm -f $(ANSIBLE_DIR)/inventory/k3s-token.txt
	rm -f backup-*/kubeconfig 2>/dev/null || true
	@echo "Secrets cleaned"
