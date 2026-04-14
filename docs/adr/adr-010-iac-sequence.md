---
status: accepted
date: 2026-04-07
tags:
  - infra
  - iac
amended: []
---

# ADR 010 - Three-Layer IaC Sequence (Terraform -> Ansible -> Helm)

## Context

The project requires provisioning VMs, bootstrapping a Kubernetes cluster,
and deploying application services. Each of these has different lifecycle
characteristics and tooling strengths.

## Decision

Infrastructure is provisioned in three sequential layers:

1. **Terraform** (`bpg/proxmox` provider) provisions 3 Ubuntu VMs from a
   cloud-init template, one per Proxmox node.
2. **Ansible** (`k3s-io/k3s-ansible`) bootstraps the k3s cluster
   with embedded etcd HA.
3. **Helm + kubectl** deploys all application services and raw Kubernetes
   manifests.

## Rationale

- The `bpg/proxmox` Terraform provider is the recommended choice - it is
  actively maintained with frequent releases and allows management of every
  aspect of a Proxmox environment. The older Telmate provider is more limited.
- The official `k3s-io/k3s-ansible` repository automatically sets up k3s in
  HA mode with embedded etcd when multiple hosts are in the server group, and
  handles kubeconfig retrieval to the control node.
- Each layer has clear responsibility boundaries: Terraform creates the
  infrastructure, Ansible configures the OS and cluster, Helm manages the application
  lifecycle. This separation prevents configuration drift and allows each layer
  to be re-run independently.

## Alternatives considered

- *Single-tool approaches:* Using Terraform alone would require provisioners
  (anti-pattern). Using Ansible alone would lose declarative state management for
  VMs. The combination leverages each tool's strength.
