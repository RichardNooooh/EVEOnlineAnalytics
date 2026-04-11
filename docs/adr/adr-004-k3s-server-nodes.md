---
status: accepted
date: 2026-03-28
tags: 
  - iac
  - k3s
amended: []
---

# ADR 004 - All k3s Nodes as Server+Workload (No Dedicated Agents)

## Context

k3s supports separate server and agent node roles. With 3 nodes and ~13 GB usable RAM 
each (~39 GB total), dedicating nodes to server-only roles would waste capacity.

## Decision

All 3 nodes run as k3s server nodes with workload scheduling enabled. The Ansible inventory has an empty `agent` group.

## Rationale

- k3s server nodes can also run workloads by default. With only 3 nodes and a constrained 
  RAM budget, every node must pull double duty.
- HA is provided by embedded etcd with 3-node quorum (tolerates 1 node failure).
- Node role (server vs. agent) is determined at k3s install time via the Ansible inventory. Changing a node's role 
  requires drain -> uninstall -> reinstall. The cosmetic label shown by `kubectl get nodes` is separate from the 
  actual running processes.

