---
status: accepted
date: 2026-03-28
tags: 
  - tools
amended: []
---

# ADR 005 - DuckDB as Primary Warehouse (with Cloud-Readiness Proofs)

## Context

The project operates under a $0/month budget target ($5/month absolute max). A warehouse is 
needed for analytical queries, dbt transformations, and ML feature engineering.

## Decision

DuckDB is the primary warehouse, running as an embedded database file on NFS-backed persistent 
storage. Snowflake and MotherDuck serve as cloud-readiness demonstrations only.

## Rationale

- DuckDB is free, requires no server process, and performs well for analytical workloads at the 
  scale of EVE market data (single-region focus on The Forge).
- Snowflake is handled via a separate Terraform directory (`terraform/snowflake/`) with its own 
  state as a cloud-readiness proof. The approach: write valid Terraform resource definitions, 
  run `tofu plan` during the 30-day trial, record a screencast of the output, then let the trial 
  expire. The IaC remains valid and reviewable.
- MotherDuck is noted as a sustainable cloud middle-ground (free tier, DuckDB-compatible) if a 
  live cloud deployment becomes desirable.
- The DuckDB file, model artifacts, and Airflow DAGs live on TrueNAS NFS, mounted as a Kubernetes 
  PersistentVolume accessible by all nodes.
