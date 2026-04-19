---
status: accepted
date: 2026-03-26
tags:
  - tools
amended:
  - 2026-04-10
  - 2026-04-13
  - 2026-04-14
  - 2026-04-18
---

# ADR 002 - Tools Used and Not Used

## Context

Every tool in the stack must have a distinct, non-overlapping purpose and a
one-sentence justification for its inclusion over alternatives. Deliberate exclusions
and the reasoning behind them are themselves part of the architecture record.

This ADR is the canonical taxonomy for the stack.

## Decision

The stack is defined by the two tables below.

### Tools in use

| Layer | Tool | Justification |
|---|---|---|
| **Orchestration** | Airflow | Industry-standard DAG orchestrator; KubernetesPodOperator enables isolated pod-per-task execution for ingestion, dbt, and ML jobs. |
| **Ingestion** | Python + dlt | Lightweight, code-first ingestion approach for everef.net archives and the ESI API. See ADR-014. |
| **Storage** | Parquet datasets on TrueNAS (ZFS RAIDZ1) + NFS | Shared storage holds the published raw and curated datasets, manifests, contracts, artifacts, and logs. Published Parquet datasets are the system of record. See ADR-016. |
| **Compute** | DuckDB (local or transient only) | Embedded analytical engine used for local development and single-writer batch jobs. DuckDB databases are scratch state, not cluster-shared persistent storage. See ADR-016. |
| **Transformation** | dbt | SQL-first transformation with built-in lineage, testing, and documentation; planned to read Parquet-backed sources and publish curated outputs. |
| **BI** | Tableau | Portfolio-standard BI tool for dashboard presentation; Tableau Public enables sharing without licensing cost. |
| **ML Experiment Tracking** | MLflow | Tracks experiments, parameters, metrics, and model artifacts; integrates cleanly with Python training scripts and serves as the model registry. |
| **ML Serving** | BentoML | Packages trained models as REST APIs with health checks and rolling restarts under k3s. |
| **Model Monitoring** | Evidently | Generates data drift and model performance reports; runs as Airflow-triggered pods rather than a persistent service. |
| **Infra Monitoring** | VictoriaMetrics + Grafana | VictoriaMetrics is a high-performance, Prometheus-compatible metrics store; Grafana provides dashboards for cluster and pipeline health. |
| **Container Platform** | k3s (Kubernetes) | Lightweight Kubernetes distribution appropriate for a 3-node homelab cluster; preserves full Kubernetes API compatibility. See ADR-003. |
| **App Deployment** | Helm | Kubernetes-native package manager; used for workloads that are intentionally deployed inside `k3s`. |
| **IaC - VM Provisioning** | OpenTofu + `bpg/proxmox` | Declarative VM provisioning via the actively maintained `bpg/proxmox` provider; OpenTofu is the open-source Terraform fork. See ADR-010. |
| **IaC - Cluster Bootstrap** | Ansible (`k3s-io/k3s-ansible`) | Handles HA etcd bootstrap, node configuration, NFS client setup, and kubeconfig retrieval. See ADR-010. |
| **Ingress** | Traefik (k3s built-in) | Bundled with k3s; routes all HTTP/S services by hostname. See ADR-012. |
| **Load Balancer** | ServiceLB / Klipper (k3s built-in) | Handles the external `LoadBalancer` service footprint required for the homelab cluster. See ADR-012. |
| **Stable API VIP** | kube-vip (DaemonSet) | Provides a stable virtual IP for `kubectl` access from the management workstation; survives individual node failure. See ADR-015. |
| **Reverse Proxy** | Caddy | Wildcard TLS termination for `*.lab.answerisnoh.dev` via Cloudflare DNS challenge; proxies to Traefik. Part of homelab base infrastructure. |
| **DNS** | Technitium (HA, 3 LXC nodes) | Self-hosted DNS with keepalived VIP; manages `normandy.internal`, `vigil.internal`, and conditional forwarding to Caddy. Part of homelab base infrastructure. |
| **Remote Access** | Twingate | Zero-trust VPN for secure remote access to the homelab; outbound-only, no inbound port forwarding. |
| **Terraform State Backend** | Garage (self-hosted S3-compatible) | AGPLv3 S3-compatible object store; hosts Terraform remote state without cloud dependency. |
| **Cloud Proof - Managed Warehouse** | Snowflake (via Terraform, trial only) | Cloud-readiness proof-of-concept; Terraform resource definitions are authored, `tofu plan` is screencasted during the trial window, then the trial is allowed to expire. |
| **Tool Version Management** | mise | Manages pinned versions of OpenTofu, Helm, Python, dbt, Ansible, and other CLI tools via `mise.toml`. |
| **Local Validation** | pre-commit | Runs repo-scoped infra checks before commit and wraps `make -C infra ...` targets for Ansible, Kubernetes YAML, and OpenTofu validation. |
| **Infra CI/CD** | GitHub Actions + self-hosted runners | Runs `.github/workflows/infra-checks.yml` for shared infrastructure validation. Current runner fleet: 3 Debian 13 LXCs hosting GitHub Actions runners. Optional support infrastructure, not a requirement for local development. |

### Tools explicitly not used

| Tool | Reason for Exclusion |
|---|---|
| **Airbyte** | Removed after evaluation. The project has two well-defined source types, does not need Airbyte's platform overhead, and is moving toward explicit single-writer dataset publication rather than syncs into a mutable destination warehouse. See ADR-014. |
| **Great Expectations** | Overlaps with dbt tests. dbt tests cover schema, business logic, freshness, and custom assertions sufficiently for this project's scope. |
| **DVC** | Published Parquet datasets, manifests, and MLflow already cover persisted analytical data and model artifacts. DVC would add a parallel versioning system with no clear incremental benefit at this scale. |
| **PowerBI** | Tableau is the sole BI tool. Adding a second BI tool provides no incremental portfolio value and splits effort. |
| **MetalLB** | ServiceLB (k3s built-in) handles the external `LoadBalancer` footprint needed here. See ADR-012. |
| **Docker Compose** | Kubernetes-managed application workloads deploy via Helm on k3s. External infrastructure services such as PostgreSQL may still run on separate Proxmox VMs. See ADR-003 and ADR-018. |
| **Terratest** | IaC scope is limited to 3 VMs and a Snowflake proof-of-concept. `tofu plan` review and Ansible idempotency checks provide sufficient validation at this scale. |
| **LXC containers for project application workloads** | Not used for the deployed project stack. Docker-in-LXC is fragile and LXCs do not provide the portability target used for k3s-managed services. Auxiliary homelab services such as GitHub Actions runners may still use LXCs. See ADR-003. |

## Amendments

- 2026-04-10 - Airbyte formally moved to "not used"
  - Airbyte was included in the original stack as the EL tool and appeared in the
    "Tools in use" table. Following the evaluation documented in ADR-014, Airbyte
    was removed from the stack entirely and moved to the "Tools explicitly not
    used" table. The original inclusion is preserved in git history.

- 2026-04-13 - Storage and compute were separated
  - The earlier taxonomy implicitly treated DuckDB as both storage and compute.
    Following ADR-016, the stack now distinguishes shared storage from local or
    transient compute. Parquet datasets on shared NFS are the persisted system of
    record. DuckDB remains in the stack as a local analytical engine only.

- 2026-04-14 - Infra validation tooling was documented explicitly
  - `pre-commit` is now part of the documented local validation path for
    infrastructure changes.
  - GitHub Actions running on self-hosted Debian 13 LXC runners is now recorded
    as optional shared CI support infrastructure rather than as part of the
    deployed application substrate.

- 2026-04-18 - Clarify k3s versus external infrastructure scope
  - Helm is documented as the deployment path for Kubernetes-managed workloads,
    not for every stateful dependency in the homelab.
  - External PostgreSQL is now explicitly treated as a separate Proxmox VM
    rather than another service deployed inside `k3s`.
