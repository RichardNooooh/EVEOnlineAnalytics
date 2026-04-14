---
status: accepted
date: 2026-04-07
tags:
  - infra
  - k3s
amended: []
---

# ADR 013 - k3s Defaults (Traefik + ServiceLB) over MetalLB

## Context

Early architecture discussions included MetalLB as the load balancer for assigning
stable LAN IPs to services. Upon review, MetalLB was never an explicit project
decision - it was an AI-suggested default that propagated through documentation unchallenged.

## Decision

Keep k3s built-in defaults: Traefik as the ingress controller and ServiceLB (Klipper) as
the load balancer. MetalLB is not used.

## Rationale

- All HTTP services (Airflow UI, Grafana, MLflow) are exposed as Ingress resources routed
 *through Traefik. There is only one LoadBalancer service that needs an external IP:
  Traefik itself. ServiceLB handles this with zero configuration.
- MetalLB adds value when many services each need their own dedicated IPs, or when BGP
  integration with network hardware is required. Neither applies here.
- Keeping k3s defaults (not passing `--disable traefik` or `--disable servicelb`) reduces
  components and configuration surface area.
- Caddy (the existing reverse proxy) proxies `*.lab.answerisnoh.dev` to any node IP on
  ports 80/443, and Traefik routes based on hostname to the correct service.
- The project aims to be self-contained. Using Traefik (bundled with k3s) rather than
  depending on external infrastructure supports that goal.

## Alternatives considered

- *MetalLB:* Would assign each service its own dedicated LAN IP from a reserved range
  (via ARP announcements). Adds operational complexity and a Helm chart for a capability
  the project doesn't need. Can be added later if a non-HTTP service requires its own
  dedicated LAN IP.
