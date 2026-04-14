---
status: accepted
date: 2026-03-28
tags:
  - infra
amended: []
---

# ADR 008 - Homelab over WSL2 for Development Environment

## Context

The full project stack (Airflow, MLflow, BentoML, Evidently, VictoriaMetrics,
Grafana, DuckDB) requires substantial compute and memory resources running
concurrently. The two candidate environments were WSL2 on a 32 GB Windows
workstation and a 3-node Proxmox homelab cluster (16 GB RAM per node).

## Decision

Deploy the entire stack on the Proxmox homelab cluster. Subsequently, a full week
was invested in configuring the homelab.

## Rationale

- WSL2 defaults to half of system memory (~16 GB), and with browser and
  OS overhead, effective available RAM drops to ~8–10 GB. Even Airflow alone consumes
  approximately 1.24 GB idle, and the full stack (Airflow, MLflow, Grafana,
  VictoriaMetrics, BentoML, Evidently, DuckDB) requires substantially more than
  what WSL2 can provide after OS overhead.
- Airflow's official documentation states that Windows environments (including WSL2)
  should only be used for development, not production - undermining the portfolio's
  "production-grade" framing.
- Even idle, Airflow's core components consume approximately 1.24 GB RAM, and this
  fluctuates significantly under load.
- The Proxmox cluster provides ~39 GB total usable RAM with real resource isolation,
  persistent NFS storage via TrueNAS, and a deployment topology that mirrors production distributed systems.
