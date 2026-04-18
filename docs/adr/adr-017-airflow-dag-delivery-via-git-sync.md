---
status: accepted
date: 2026-04-18
tags:
  - infra
  - airflow
  - gitops
  - storage
amended: []
---

# ADR 017 - Airflow DAG Delivery via git-sync in Homelab k3s

## Context

The project runs Airflow on a homelab `k3s` cluster backed by TrueNAS NFS for shared
durable storage. DAGs are expected to change frequently while the orchestration layer is
still being iterated on, so the deployment path should favor a tight GitOps feedback
loop over persistent in-cluster DAG storage.

Two alternative patterns were considered for DAG delivery:

- storing DAGs on a PVC mounted into Airflow
- baking DAGs into the Airflow image

For this project, both alternatives are a worse fit than syncing DAG code directly from
Git.

Persistent DAG storage adds state the project does not need. In this homelab, using a
PVC for DAG files also creates avoidable operational risk when the underlying storage is
an NFS-backed volume on TrueNAS. That includes bursty I/O, delayed file visibility,
sync lag, and other difficult-to-reason-about runtime behavior. The project already uses
shared NFS for durable artifacts such as published datasets, manifests, MLflow
artifacts, and Airflow logs. DAG source code should not be treated as part of that
durable storage contract.

## Decision

For the homelab `k3s` deployment, Airflow DAGs will be delivered with `git-sync` from
Git.

The deployment contract is:

- Airflow loads DAGs from a `git-sync` managed working tree.
- DAGs are not stored on a PVC.
- DAGs are not baked into the Airflow image.
- Shared NFS remains appropriate for Airflow logs, but not for DAG persistence.

Some sync delay is acceptable as a tradeoff for a simpler GitOps workflow and a cleaner
runtime storage model.

## Rationale

- `git-sync` keeps the DAG deployment path aligned with the GitOps workflow already used
  for infrastructure and application changes.
- DAG iteration is faster because changes can be delivered by normal Git updates rather
  than by rebuilding images or managing persistent DAG volumes.
- The decision preserves a clearer boundary between durable shared storage and runtime
  code delivery.
- Avoiding persistent DAG storage reduces the chance of NFS-related behavior affecting
  Airflow's DAG discovery and refresh cycle.

## Consequences

### Positive

- DAG delivery stays Git-native and easy to iterate on.
- Airflow avoids an unnecessary persistent volume for orchestration code.
- Shared NFS is reserved for durable artifacts that actually need persistence.

### Negative

- DAG updates are visible only after the next `git-sync` refresh.
- Airflow DAG delivery depends on Git availability and the required access credentials.
- Emergency hotfixes made only inside a running pod are not part of the deployment
  model.

## Alternatives Considered

- *Store DAGs on a PVC:* Rejected because it adds unnecessary persistence and is a poor
  fit for DAG delivery on TrueNAS-backed NFS storage in this homelab.
- *Bake DAGs into the Airflow image:* Rejected because it slows DAG iteration and ties
  routine orchestration changes to image build and rollout cycles.
