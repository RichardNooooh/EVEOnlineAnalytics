---
status: accepted
date: 2026-05-22
tags:
  - repo
  - platform
  - workload
  - portfolio
amended: []
---

# ADR-001 - Split Workload and Platform Repositories

## Context

This repository is now the analytics workload repository, `eve-market-analytics`.
The companion platform repository is `homelab-data-platform`.

Before the split, the project mixed two related but different concerns:

- the analytics workload itself, including ingestion, dataset contracts, dbt
  transforms, orchestration logic, and experiments
- the reusable homelab platform used to run that workload, including Proxmox,
  k3s, shared storage wiring, Airflow runtime patterns, and monitoring

That mixed structure made early iteration easy, but it now creates two problems.

First, it weakens portfolio clarity. A reviewer opening the repository must
parse both the product-level data engineering story and the platform-level
homelab story at the same time. The current root README is heavily runtime- and
deployment-oriented, which makes the main analytics workload less visible than
it should be.

Second, it blurs architectural boundaries. Reusable platform concerns and
workload-specific concerns are both checked into one tree, which encourages
monorepo-relative path assumptions, deployment coupling, and documentation that
mixes stable workload contracts with homelab-specific runtime details.

The project still needs both stories:

- a flagship analytics workload portfolio artifact
- a reusable self-hosted data platform artifact

The split should improve both presentation and boundary quality without
reintroducing source coupling through git submodules or duplicated workload
repositories.

## Decision

Adopt and maintain the split into **two primary repositories**.

### 1. Analytics Workload Repository

The workload-first repository is `eve-market-analytics`.

This repository owns:

- ingestion code and tests
- dbt transform code and tests
- Airflow DAGs and workload orchestration logic
- dataset contracts, manifests, and data semantics documentation
- experiments and validation evidence
- workload-focused ADRs and architecture docs
- workload image builds and workload CI
- the reviewer-friendly local development and demo path needed to understand and
  run the analytics pipeline

This repository becomes the primary portfolio artifact.

### 2. Homelab Platform Repository

The reusable platform repository is `homelab-data-platform`.

This repository owns:

- Proxmox and OpenTofu provisioning
- Ansible bootstrap for base OS, k3s, and supporting services
- reusable shared-storage and runtime patterns
- reusable Airflow runtime deployment patterns
- monitoring and platform operations assets
- platform-focused ADRs and architecture docs
- platform CI and validation

This repository becomes a supporting artifact that demonstrates reusable
self-hosted runtime engineering.

### Integration Rules

- Do **not** use git submodules.
- Do **not** duplicate the workload into a separate cloud-target repository.
- Integrate the two repositories through versioned artifacts and documented
  runtime contracts, such as container image tags or digests, required mounts,
  required secrets, and environment-variable-based service wiring.
- If cloud deployment is added later, prefer a thin environment overlay or
  deploy repository over a second copy of the workload code.

### Boundary Rules

- Workload-specific DAGs stay with the analytics repository.
- Dataset semantics, publication contracts, and transform logic stay with the
  analytics repository.
- Reusable cluster bootstrap, storage, monitoring, and service deployment
  patterns stay with the platform repository.
- The analytics repository may keep a local Docker or Compose-based review path
  even if the production-style runtime is documented in the platform repository.

## Consequences

### Positive

- The analytics repository can present a much clearer portfolio story centered
  on ingestion, publication semantics, transformation, and analytics outputs.
- The platform repository can present a cleaner self-hosted infrastructure story
  without carrying domain-specific workload code.
- The split forces clearer runtime contracts between workload and platform.
- The project can reuse the platform repository for future data workloads
  without carrying the market analytics domain with it.
- Workload docs and platform docs can stop blending concerns in the same entry
  points.

### Negative

- The split introduces migration work, including path cleanup, CI changes,
  README rewrites, and doc reorganization.
- Cross-repository changes will need explicit version coordination.
- Some current files, especially local runtime and deployment assets, will need
  careful judgment to decide whether they are workload-specific or reusable.
- Reviewers will need cross-links between repositories to understand the full
  platform-plus-workload story.

## Operational Notes

- Operate with exactly two repositories: `eve-market-analytics` and
  `homelab-data-platform`.
- Defer any cloud-target repository decision until the active two-repository
  split is stable.
- Preserve git history only where it is easy and does not add major migration
  complexity.
- Remove monorepo-relative path assumptions during the split, especially in
  local orchestration and transform configuration.
- Keep at least one low-friction local review path in the analytics repository.
- During migration, some platform-oriented files may remain temporarily in this
  repository until they are extracted into `homelab-data-platform`.
- `infra/local/` remains in this repository for now as the local analytics
  review and demo harness.

## Alternatives Considered

- *Stay monorepo:* Rejected. It keeps end-to-end code in one place, but the
  mixed portfolio story and blurred platform/workload boundary now cost more
  than the convenience is worth.
- *Split into three full repositories now:* Rejected. A separate cloud-target
  workload repository would likely duplicate pipeline code and create drift
  before the homelab/platform split has stabilized.
- *Use git submodules for cross-repository composition:* Rejected. Submodules
  create a worse reviewer experience, more awkward local setup, and fragile
  cross-repository update flows.
- *Make the platform repository the primary public artifact:* Rejected. The
  workload repository should remain the main portfolio entry point because it is
  the clearest demonstration of data engineering value.
