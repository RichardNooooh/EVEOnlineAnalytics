---
status: accepted
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

## Decision

Use an external PostgreSQL instance for the Airflow metadata database.

The architecture contract is:

- Airflow does not use the Helm chart's embedded PostgreSQL dependency for its
  metadata database.
- Airflow connects to an external PostgreSQL service for metadata storage.
- This ADR defines the metadata database direction and operational boundary. It does
  not itself implement the change.

## Rationale

- The external database posture is a better fit for a production-oriented Airflow
  deployment than an embedded chart dependency. It creates a cleaner separation between
  orchestration services and stateful database operations.
- Using an external PostgreSQL service makes the metadata tier a first-class
  infrastructure dependency instead of a convenience subcomponent hidden inside the
  Helm release.
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
  PostgreSQL is treated as an explicit infrastructure service.
- The architecture follows the documented production direction of the Airflow Helm
  chart rather than relying on its embedded convenience dependency.

### Negative

- The deployment depends on an external database service rather than a simpler embedded
  chart dependency.
- Backup, availability, upgrades, and secret management for the metadata database are
  now explicit operational responsibilities.

## Alternatives Considered

- *Embedded PostgreSQL from the Airflow Helm chart:* Rejected because it is a better fit
  for easier testing and standalone use than for the production-oriented direction of
  this homelab deployment.
- *External PostgreSQL with PgBouncer from the start:* Deferred. PgBouncer is tracked as
  a separate follow-on architecture decision in ADR-019 rather than being accepted as
  part of the baseline metadata database contract here.
