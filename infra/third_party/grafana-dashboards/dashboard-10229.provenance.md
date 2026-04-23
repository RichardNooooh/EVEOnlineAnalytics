# Dashboard 10229 Provenance

- Dashboard: Grafana dashboard 10229, `VictoriaMetrics - single-node`
- Local vendored JSON: `infra/k8s/monitoring/dashboards/grafana-dashboard-10229-victoriametrics-single-node.json`
- Local Kustomize source: `infra/k8s/monitoring/kustomization.yaml`
- Local rendered ConfigMap JSON file: `infra/k8s/monitoring/rendered/grafana-dashboards.json`
- Grafana page: `https://grafana.com/grafana/dashboards/10229-victoriametrics-single-node/`
- Grafana JSON download: `https://grafana.com/api/dashboards/10229/revisions/latest/download`
- Upstream source repository: `https://github.com/VictoriaMetrics/VictoriaMetrics`
- Upstream source file: `https://raw.githubusercontent.com/VictoriaMetrics/VictoriaMetrics/master/dashboards/victoriametrics.json`
- Upstream license: Apache-2.0, vendored in `dashboard-10229.LICENSE.txt`
- Upstream NOTICE file: none found for this dashboard asset

Local normalization:

- Set dashboard `id` to `null` for file provisioning.
- Pinned the datasource variable `ds` to the checked-in Grafana datasource UID `victoriametrics` so the sidecar-provisioned dashboard binds to the repo-managed datasource without folder-specific Grafana config.
