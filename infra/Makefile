# Infrastructure Automation Makefile
# Proxmox Infrastructure Management

.PHONY: help vms cluster deploy-all plan init fmt validate clean bootstrap inventory ips status nfs helm-repos deploy-airbyte deploy-airflow deploy-mlflow deploy-monitoring

# Default target
help:
	@echo "Infrastructure Management Commands:"
	@echo "  make init       - Initialize OpenTofu"
	@echo "  make plan       - Plan infrastructure changes"
	@echo "  make vms        - Create/update k3s VMs on Proxmox"
	@echo "  make cluster    - Bootstrap k3s cluster with Ansible"
	@echo "  make deploy-all - Deploy all services to k8s"
	@echo "  make fmt        - Format OpenTofu files"
	@echo "  make validate   - Validate OpenTofu configuration"
	@echo "  make clean      - Remove OpenTofu state and lock files"

# Initialize Terraform
init:
	cd terraform/proxmox && tofu init

# Plan infrastructure changes
plan: init
	cd terraform/proxmox && tofu plan

# Create/Update VMs on Proxmox
vms: init
	cd terraform/proxmox && tofu apply -auto-approve
	@echo ""
	@echo "VMs created. Next step: make cluster"

# Bootstrap k3s cluster (requires VMs to exist)
cluster:
	@echo "Bootstrapping k3s cluster with Ansible..."
	cd ansible && ansible-playbook -i inventory/hosts.yml playbooks/k3s-init.yml

# Configure NFS client on all nodes
nfs:
	cd ansible && ansible-playbook -i inventory/hosts.yml playbooks/nfs-client.yml

helm-repos:
	helm repo add airbyte https://airbytehq.github.io/helm-charts
	helm repo add apache-airflow https://airflow.apache.org
	helm repo add community-charts https://community-charts.github.io/helm-charts
	helm repo add vm https://victoriametrics.github.io/helm-charts
	helm repo add grafana https://grafana.github.io/helm-charts
	helm repo update

# Deploy all k8s services
deploy-all: helm-repos
	@echo "Deploying k8s base resources..."
	kubectl apply -f k8s/namespaces.yaml
	kubectl apply -f k8s/metallb-config.yaml
	kubectl apply -f k8s/nfs-pv.yaml
	@echo ""
	@echo "Deploying Helm charts..."
	$(MAKE) deploy-airbyte
	$(MAKE) deploy-airflow
	$(MAKE) deploy-mlflow
	$(MAKE) deploy-monitoring

deploy-airbyte:
	@echo "Deploying Airbyte..."
	helm upgrade --install airbyte airbyte/airbyte \
	    --values helm/airbyte-values.yaml \
	    --namespace data --create-namespace

deploy-airflow:
	@echo "Deploying Airflow..."
	helm upgrade --install airflow apache-airflow/airflow \
	    --values helm/airflow-values.yaml \
	    --namespace data --create-namespace

deploy-mlflow:
	@echo "Deploying MLflow..."
	helm upgrade --install mlflow community-charts/mlflow \
	    --values helm/mlflow-values.yaml \
	    --namespace ml --create-namespace

deploy-monitoring:
	@echo "Deploying monitoring stack..."
	helm upgrade --install victoriametrics vm/victoria-metrics-single \
	    --values helm/victoriametrics-values.yaml \
	    --namespace monitoring --create-namespace
	helm upgrade --install grafana grafana/grafana \
	    --values helm/grafana-values.yaml \
	    --namespace monitoring --create-namespace

# Terraform formatting
fmt:
	cd terraform/proxmox && tofu fmt

# Terraform validation
validate: init
	cd terraform/proxmox && tofu validate

# Clean up temporary files
clean:
	@echo "WARNING: Deleting OpenTofu state..."
	read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ]
	cd terraform/proxmox && rm -f terraform.tfstate* .terraform.lock.hcl
	rm -rf terraform/proxmox/.terraform

# Full bootstrap (VMs → k3s → services)
bootstrap: vms cluster deploy-all
	@echo "Full bootstrap complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Configure DNS entries for services"
	@echo "  2. Run data ingestion pipelines"
	@echo "  3. Deploy Tableau workbooks"

# Generate Ansible inventory from Terraform
inventory:
	cd terraform/proxmox && tofu output k3s_inventory > ../../ansible/inventory/hosts.yml
	@echo "Ansible inventory generated at ansible/inventory/hosts.yml"

# Show VM IPs
ips:
	cd terraform/proxmox && tofu output k3s_all_nodes

# Show connection info
status:
	@echo "=== Proxmox VMs ==="
	cd terraform/proxmox && tofu output vm_names 2>/dev/null || echo "No VMs deployed yet"
	@echo ""
	@echo "=== k8s Nodes ==="
	kubectl get nodes 2>/dev/null || echo "k3s cluster not accessible"
	@echo ""
	@echo "=== Service Status ==="
	kubectl get pods --all-namespaces 2>/dev/null | head -20 || echo "Services not deployed"
