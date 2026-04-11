---
status: accepted
date: 2026-03-26
tags:
  - tools
amended:
  - 2026-04-10
---

# ADR 002 - Tools Used and Not Used

## Context

Every tool in the stack must have a distinct, non-overlapping purpose and 
a one-sentence justification for its inclusion over alternatives. Deliberate 
exclusions - and the reasoning behind them - are themselves a signal of 
engineering maturity. This ADR serves as the canonical record of what is and 
is not in the stack.

## Decision

The stack is defined by the two tables below.

### Tools in use

| Layer | Tool | Justification |
|---|---|---|
| **Orchestration** | Airflow | Industry-standard DAG orchestrator; KubernetesPodOperator enables isolated pod-per-task execution for dbt and ML training jobs. |
| **Transformation** | dbt | SQL-first transformation with built-in lineage, testing, and documentation; the standard tool for the warehouse transformation layer. |
| **Warehouse** | DuckDB (local, NFS-backed PV) | Free, embedded, high-performance analytical database appropriate for single-region EVE market data volume; no server process required. See ADR-005. |
| **BI** | Tableau | Portfolio-standard BI tool for dashboard presentation; Tableau Public enables sharing without licensing cost. |
| **ML Experiment Tracking** | MLflow | Tracks experiments, parameters, metrics, and model artifacts; integrates cleanly with Python training scripts and serves as the model registry. |
| **ML Serving** | BentoML | Packages trained models as REST APIs with health checks and rolling restarts under k3s. |
| **Model Monitoring** | Evidently | Generates data drift and model performance reports; runs as Airflow-triggered pods rather than a persistent service. |
| **Infra Monitoring** | VictoriaMetrics + Grafana | VictoriaMetrics is a high-performance, Prometheus-compatible metrics store; Grafana provides dashboards for cluster and pipeline health. |
| **Container Platform** | k3s (Kubernetes) | Lightweight Kubernetes distribution appropriate for a 3-node homelab cluster; preserves full Kubernetes API compatibility. See ADR-003. |
| **App Deployment** | Helm | Kubernetes-native package manager; used for all application service deployments. |
| **IaC - VM Provisioning** | OpenTofu + `bpg/proxmox` | Declarative VM provisioning via the actively maintained `bpg/proxmox` provider; OpenTofu is the open-source Terraform fork. See ADR-010. |
| **IaC - Cluster Bootstrap** | Ansible (`k3s-io/k3s-ansible`) | Official k3s Ansible playbook; handles HA etcd bootstrap and kubeconfig retrieval automatically. See ADR-010. |
| **Ingestion** | Python + dlt | Lightweight, code-first ingestion library; appropriate for the two-source use case (everef.net CSVs + ESI REST API). See ADR-013. |
| **Ingress** | Traefik (k3s built-in) | Bundled with k3s; routes all HTTP/S services by hostname. See ADR-012. |
| **Load Balancer** | ServiceLB / Klipper (k3s built-in) | Handles the single external LoadBalancer service (Traefik); zero configuration required. See ADR-012. |
| **Stable API VIP** | kube-vip (DaemonSet) | Provides a stable virtual IP for `kubectl` access from the management workstation; survives individual node failure. See ADR-014. |
| **Reverse Proxy** | Caddy | Wildcard TLS termination for `*.lab.answerisnoh.dev` via Cloudflare DNS challenge; proxies to Traefik. Part of homelab base infrastructure. |
| **DNS** | Technitium (HA, 3 LXC nodes) | Self-hosted DNS with keepalived VIP; manages `normandy.internal`, `vigil.internal`, and conditional forwarding to Caddy. Part of homelab base infrastructure. |
| **Remote Access** | Twingate | Zero-trust VPN for secure remote access to homelab; outbound-only, no inbound port forwarding. |
| **Storage** | TrueNAS (ZFS RAIDZ1) + NFS | NFS-exported PersistentVolumes for DuckDB, model artifacts, and Airflow DAGs shared across all k3s nodes. |
| **Terraform State Backend** | Garage (self-hosted S3-compatible) | AGPLv3 S3-compatible object store; hosts Terraform remote state without cloud dependency. |
| **Cloud Proof - Warehouse** | Snowflake (via Terraform, trial only) | Cloud warehouse proof-of-concept; Terraform resource definitions authored, `tofu plan` screencasted during 30-day trial, trial allowed to expire. IaC remains valid and reviewable. |
| **Tool Version Management** | mise | Manages pinned versions of OpenTofu, Helm, Python, dbt, Ansible, and other CLI tools via `mise.toml`. |


### Tools explicitly not used

| Tool | Reason for Exclusion |
|---|---|
| **Airbyte** | Removed after evaluation (see ADR-013). Three compounding problems: Airbyte's own documentation states that local file-based DBs (including DuckDB) will not work on Kubernetes; base components consume 6–8 GB RAM on a memory-constrained cluster; and the ingestion use case (downloading CSVs from everef.net and polling the ESI API) is better served by Python scripts running directly in Airflow DAGs. |
| **Great Expectations** | Overlaps with dbt tests. Since Great Expectations was cut, dbt tests are the entire data quality story. The dbt test suite includes not-null, unique, accepted-values, custom tests (no negative prices, volume > 0), and referential integrity checks. |
| **DVC** | The warehouse (DuckDB) combined with MLflow serves as the versioned data and model store. DVC would add a parallel versioning system with no incremental benefit. Model artifacts (`.pkl`, `.joblib`, `.onnx`, etc.) are logged to MLflow, not committed to git. |
| **PowerBI** | Tableau is the sole BI tool. Adding a second BI tool provides no incremental portfolio value and splits effort. |
| **MetalLB** | ServiceLB (k3s built-in) handles the single LoadBalancer service needed (Traefik). See ADR-012. |
| **Docker Compose** | All services deploy via Helm on k3s. See ADR-003. |
| **Terratest** | IaC scope is 3 VMs and a Snowflake proof-of-concept. Terratest's value scales with module complexity and multi-environment promotion. At this project's scale, `tofu plan` output review and Ansible idempotency checks provide sufficient validation. Would add for shared Terraform modules in a team context. |
| **LXC containers** | Not officially supported by Proxmox for Docker workloads. No cloud portability story. See ADR-003. |


## Amendments

- 2026-04-10 - Airbyte formally moved to "not used"
  - Airbyte was included in the original stack as the EL tool and appeared in 
    the "Tools in use" table. Following the evaluation documented in ADR-014, 
    Airbyte was removed from the stack entirely. It has been moved to the "Tools 
    explicitly not used" table above, with the removal date of 2026-04. The 
    original inclusion of Airbyte is preserved in git history. ADR-014 contains 
    the full rationale for its removal.
