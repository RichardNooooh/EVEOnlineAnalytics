---
status: accepted
date: 2026-03-26
tags:
  - tools
  - k3s
  - docker
amended:
  - 2026-04-10
  - 2026-04-14
  - 2026-04-18
---

# ADR 003 - k3s on Kubernetes over Docker Compose

## Context

The project initially considered Docker Compose inside one or two Proxmox VMs as the containerization
strategy. Airbyte, as of version 2.0, strongly encouraged Helm chart V2 for new deployments and no longer
supported Docker Compose as a production deployment path — making k3s the natural choice for a stack that included Airbyte.

## Decision

Deploy Kubernetes-managed application workloads on a 3-node k3s cluster managed via
Helm charts. External infrastructure services may still run on separate Proxmox VMs.
No Docker Compose files exist in the project.

## Rationale

- Kubernetes skills are increasingly expected in data engineering and MLOps roles. Operating a real k3s cluster
  with Helm charts, resource limits, PersistentVolumes, and Ingress resources demonstrates operational maturity that
  Docker Compose cannot.
- Airbyte V2's strong preference for Helm chart deployment made k3s the path of least resistance for the original
  stack.
- k3s is lightweight enough to run on the 3-node homelab cluster without significant overhead, while preserving full
  Kubernetes API compatibility.

## Alternatives considered

- *Docker Compose in Proxmox VMs*: Simpler operationally and offers a direct translation path to AWS ECS via the Amazon
  ECS CLI. Rejected primarily because Airbyte no longer supported it as a production deployment path, and because it lacks
  native equivalents for pod scheduling, resource limits, health-check-based restarts, and the KubernetesPodOperator pattern.
- *LXC containers for project application workloads*: Not officially supported by Proxmox for Docker workloads (nesting Docker
  inside LXC is fragile and may break on updates). Offers no portability to cloud environments.

## Amendments

- 2026-04-10 - Rejustifying k3s after Airbyte removal
  - Airbyte was removed from the stack entirely after ADR-014. The original forcing function for k3s (Airbyte's Helm-only
    deployment path) no longer applies. The decision to retain k3s was re-evaluated and upheld on independent grounds:
    1. The IaC infrastructure supporting k3s — Terraform VM provisioning, cloud-init templates, Ansible k3s bootstrap,
       kube-vip DaemonSet, Traefik ingress configuration — was already built and operational. Switching to Docker Compose
       would require reworking or discarding completed infrastructure work without corresponding benefit.
    2. The remaining services benefit from k3s capabilities independently of Airbyte. Airflow's KubernetesPodOperator can
       run dbt and ML training jobs as isolated pods. BentoML's serving container gets health checks, rolling restarts, and
       resource limits natively. Evidently runs as Airflow-triggered pods rather than needing a persistent container.
    3. Removing Airbyte freed 6–8 GB from the RAM budget, giving the remaining services significantly more headroom — making
       k3s more viable than before, not less.
  - The Docker Compose alternative was re-evaluated and again rejected: the k3s IaC was already built, switching would represent
    regression rather than progress, and Docker Compose lacks the KubernetesPodOperator pattern the pipeline depends on.

- 2026-04-14 - Scope the LXC rejection to application workloads
  - The LXC rejection in this ADR applies to running the project application
    stack as Docker or Compose workloads.
  - It does not prohibit auxiliary homelab services from using LXCs. The current
    infra validation runner fleet uses 3 Debian 13 LXCs hosting GitHub Actions
    self-hosted runners while the project workloads still run on k3s VMs.

- 2026-04-18 - Clarify that external infrastructure can sit outside k3s
  - The k3s decision remains the deployment path for Kubernetes-managed
    workloads.
  - It does not require every supporting infrastructure dependency to run inside
    the cluster. The PostgreSQL direction in ADR-018 uses a separate Proxmox VM.
