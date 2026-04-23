# Third-Party Grafana Dashboards

This directory scopes license and provenance records for vendored community Grafana
dashboards used by `infra/k8s/monitoring/kustomization.yaml`.

Only the vendored dashboard assets and notices referenced here are covered by the
upstream MIT or Apache-2.0 licenses. The repository as a whole is not relicensed by
including these files.

Checked-in dashboards:

- `grafana-dashboard-315-kubernetes-cluster-monitoring-via-prometheus.json`
- `grafana-dashboard-10229-victoriametrics-single-node.json`

The vendored JSON files are rendered into Grafana dashboard ConfigMaps by
`make render-monitoring-manifests`, which writes the generated JSON file to
`infra/k8s/monitoring/rendered/grafana-dashboards.json`.
