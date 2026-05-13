# infra/AGENTS.md

Read this when changing OpenTofu, Ansible, Kubernetes manifests, Helm values, storage,
or monitoring deployment assets.

## Read First

- `../AGENTS.md`
- `../docs/architecture.md`
- `../docs/storage_layout.md`
- `../docs/data_lifecycle.md`
- Relevant ADRs before changing architecture contracts

## Platform Contract

- Kubernetes workloads run on a 3-node k3s cluster across a Proxmox homelab.
- All 3 nodes are k3s server nodes with workload scheduling enabled.
- TrueNAS NFS is exposed to the cluster through RWX PersistentVolumes.
- Shared NFS stores DuckLake data files, manifests/contracts, MLflow artifacts, and
  Airflow logs.
- DuckLake catalog metadata should use PostgreSQL for production-style deployments.
- Airflow metadata uses an external PostgreSQL server on its own Proxmox VM.
- DuckDB work databases must be local or transient scratch only, never shared NFS.

## IaC Layers

- `terraform/proxmox/`: OpenTofu provisions the 3 Debian 13 VMs.
- `ansible/`: bootstraps k3s, installs NFS client utilities, verifies shared storage.
- `k8s/` and `helm/`: namespaces, shared NFS storage contracts, service deployments.

## Helm Rules

- Helm values follow `helm/<service>.yml`, such as `airflow.yml` and
  `mlflow.yml`.
- Resource requests and limits must be set in every Helm values file.
- Use `helm/grafana.yml` plus Kubernetes dashboard ConfigMaps/manifests for
  checked-in Grafana dashboards.

## Snowflake

- Snowflake IaC is a cloud-readiness path only.
- Create `terraform/snowflake/` only when explicitly asked for cloud-readiness IaC
  beyond the Proxmox stack.
- Steady state remains self-hosted DuckLake tables backed by Parquet files plus local
  or transient compute.

## RAM Budget

| Component | Estimated Memory | Notes |
|---|---|---|
| k3s overhead (x3) | ~1.5 GB | ~512 MB per server node |
| Airflow | 2-3 GB | Webserver + scheduler + worker |
| MLflow | 0.5-1 GB | Tracking server only |
| Grafana | 0.5 GB | Lightweight |
| VictoriaMetrics | 0.5-1 GB | Single-node mode |
| DuckDB work DBs | 1-2 GB | Depends on active batch/query workload |
| BentoML | 0.5-1 GB | Model serving |
| Evidently | 0.5 GB | Periodic workload |
| Headroom | ~26-32 GB | Burst capacity and OS cache |
