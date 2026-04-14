---
status: accepted
date: 2026-04-11
tags:
  - infra
  - k3s
amended: []
---

# ADR 015 - kube-vip DaemonSet for Stable API Endpoint

## Context

With 3 k3s server nodes and embedded etcd, the cluster survives a single node
failure. However, `kubectl` access from the management workstation requires a
`server:` URL in the kubeconfig. Without a VIP, this points to a single node
IP - if that node goes down, `kubectl` fails even though the cluster is healthy.

## Decision

Deploy kube-vip as a DaemonSet after cluster bootstrap to provide a stable
virtual IP for the Kubernetes API endpoint.

## Rationale

- k3s has a built-in client-side load balancer: once the cluster is formed,
  each node's internal agent discovers all API server endpoints and can failover
  automatically. A VIP is not strictly necessary for intra-cluster communication.
- The VIP's primary value is a stable external `kubectl` endpoint from the
  management workstation and robust node re-registration after wipe/reprovision cycles.
- kube-vip works differently on k3s than on kubeadm clusters: k3s can bootstrap a
  single server without the VIP existing first, so kube-vip deploys as a DaemonSet into
  an already-running cluster.
- The `--tls-san=<VIP>` flag must be passed at k3s install time so the API server
  certificate includes the VIP address.
- Placing RBAC and DaemonSet manifests in `/var/lib/rancher/k3s/server/manifests/`
  causes k3s to auto-apply them.

**Deployment sequence:** Terraform → Ansible (k3s install with `--tls-san`, then template
kube-vip manifests to first server node) → k3s auto-applies manifests.
