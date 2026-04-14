---
status: accepted
date: 2026-04-07
tags:
  - infra
  - iac
amended: []
---

# ADR 009 - Separate Terraform State for Homelab Base Infrastructure

## Context

The homelab includes base infrastructure (Technitium DNS, Caddy reverse proxy,
Proxmox cluster configuration) that serves the entire homelab, not just the
EVE project. The EVE project's Terraform manages only its own k3s VMs.

## Decision

Homelab base infrastructure and the EVE project live in separate Terraform
projects with separate state files, in separate repositories.

## Rationale

- Different lifecycles: base infrastructure changes infrequently and serves all
  homelab projects; EVE project VMs are iterated on frequently during development.
- Different blast radii: a bad `tofu apply` on EVE project VMs should not be
  able to disrupt DNS, reverse proxy, or Proxmox cluster configuration.
- This separation is itself a portfolio signal - it demonstrates understanding
  of state isolation and blast radius management in production Terraform workflows.
