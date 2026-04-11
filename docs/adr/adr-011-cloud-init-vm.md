---
status: accepted
date: 2026-04-07
tags: 
  - iac
amended: []
---

# ADR 011 - cloud-init for First-Boot VM Setup

## Context

VMs provisioned by Terraform need an initial bootstrap to become SSH-reachable 
by Ansible. This includes creating a service user, injecting SSH keys, and 
installing minimal prerequisites.

## Decision

Use a custom cloud-init `user-data.yaml` (Debian 13 "Trixie") uploaded as a 
Proxmox snippet via the `bpg/proxmox` provider's `proxmox_virtual_environment_file` 
resource. cloud-init handles:

- `ansible` OS user with passwordless sudo + SSH key auth
- Minimal packages: `qemu-guest-agent`, `nfs-common`, `python3`
- SSH hardening drop-in config

Networking (static IP) and hostname are set via Proxmox's `ipconfig0` and 
`vm_name` in Terraform, not in cloud-init.
