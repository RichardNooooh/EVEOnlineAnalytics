---
status: deferred
date: 2026-04-18
tags:
  - infra
  - airflow
  - postgresql
amended: []
---

# ADR 018 - External PostgreSQL for Airflow Metadata

## Context

This project runs Airflow on a homelab `k3s` cluster as part of a production-shaped,
self-hosted data engineering and MLOps platform. The goal is not to document a
standalone test install of Airflow, but the durable infrastructure direction for the
orchestration layer used by the platform.

Airflow's Helm chart can deploy an embedded PostgreSQL dependency. The [Apache Airflow
Helm chart production guide](https://airflow.apache.org/docs/helm-chart/stable/production-guide.html)
explicitly treats that embedded database as a convenience for easier testing and
standalone use, and recommends an external database for production deployments.

This ADR is about the Airflow metadata database architecture and operational
reliability. It does not change DAG code, dbt logic, model code, or any other
application behavior.

The remaining architecture question is where that external database should run. For
this homelab, the intended deployment is a dedicated PostgreSQL server on its own
Proxmox VM rather than another stateful service inside `k3s`.

## Decision

Use an external PostgreSQL server on a separate Proxmox VM for the Airflow metadata
database.

The architecture contract is:

- Airflow does not use the Helm chart's embedded PostgreSQL dependency for its
  metadata database.
- Airflow connects to an external PostgreSQL server running outside Kubernetes on its
  own Proxmox VM.
- PostgreSQL is not deployed as another `k3s` workload or Helm release.
- The same PostgreSQL server may later host MLflow in separate databases and
  credentials, but Airflow metadata is the only confirmed use in this ADR.
- This ADR defines the metadata database direction and operational boundary. It does
  not itself implement the change.

## Rationale

- The external database posture is a better fit for a production-oriented Airflow
  deployment than an embedded chart dependency. It creates a cleaner separation between
  orchestration services and stateful database operations.
- Using an external PostgreSQL server on its own Proxmox VM makes the metadata tier a
  first-class infrastructure dependency instead of a convenience subcomponent hidden
  inside the Helm release or another in-cluster stateful workload.
- This is the production direction documented by the [Apache Airflow Helm chart
  production guide](https://airflow.apache.org/docs/helm-chart/stable/production-guide.html),
  which treats the embedded PostgreSQL dependency as suitable for easier testing and
  standalone use and recommends an external database for production deployments.
- The decision improves operational durability without changing Airflow DAG code or any
  other application logic.

## Consequences

### Positive

- Airflow metadata storage aligns with the repo's production-shaped homelab posture
  rather than a standalone test deployment path.
- Responsibility boundaries are cleaner: Airflow remains the orchestrator, while
  PostgreSQL is treated as an explicit infrastructure service on a separate Proxmox VM.
- The architecture follows the documented production direction of the Airflow Helm
  chart rather than relying on its embedded convenience dependency.
- The same PostgreSQL server can later be extended to support MLflow without changing
  the baseline decision that metadata storage lives outside the cluster.

### Negative

- The deployment depends on a separate database VM rather than a simpler embedded chart
  dependency.
- Backup, availability, upgrades, and secret management for the metadata database are
  now explicit operational responsibilities.

## Alternatives Considered

- *Embedded PostgreSQL from the Airflow Helm chart:* Temporarily accepted because it is a
  better fit for easier testing and standalone use than for the production-oriented
  direction of this homelab deployment.
- *External PostgreSQL as another `k3s` service:* Rejected because it would keep a
  critical stateful database inside the cluster instead of using a cleaner boundary with
  a dedicated Proxmox VM.
- *External PostgreSQL with PgBouncer from the start:* Deferred. PgBouncer is tracked as
  a separate follow-on architecture decision in ADR-019 rather than being accepted as
  part of the baseline metadata database contract here.
