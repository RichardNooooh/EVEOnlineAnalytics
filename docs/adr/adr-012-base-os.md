---
status: accepted
date: 2026-04-07
tags:
  - infra
  - iac
amended: []
---

# ADR 012 - Proxmox VM Base OS Choice

## Context

The underlying OS can affect how much overhead memory is used for each k3s node.

## Decision

Use Debian 13 (generic) OS image.

## Rationale

- Debian generally has a much lighter memory usage compared to something like Ubuntu.
- It also uses the systemd init system, which works well with k3s.
- Well-tested with k3s.

## Alternatives considered

- *Alpine Linux*: This is one of the lightest OS's one can use. However, it makes
  configuring the pods more difficult since Alpine uses `musl libc` instead of `glibc`.
  Also makes it more difficult to use `nfs`. And compared to Debian, the memory benefit
  is minimal compared to the amount of work required to get every other component working.
