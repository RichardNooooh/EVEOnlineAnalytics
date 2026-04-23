# Dashboard 315 Provenance

- Dashboard: Grafana dashboard 315, `Kubernetes cluster monitoring (via Prometheus)`
- Local vendored JSON: `infra/k8s/monitoring/dashboards/grafana-dashboard-315-kubernetes-cluster-monitoring-via-prometheus.json`
- Local Kustomize source: `infra/k8s/monitoring/kustomization.yaml`
- Local rendered ConfigMap JSON file: `infra/k8s/monitoring/rendered/grafana-dashboards.json`
- Grafana page: `https://grafana.com/grafana/dashboards/315-kubernetes-cluster-monitoring-via-prometheus/`
- Grafana JSON download: `https://grafana.com/api/dashboards/315/revisions/latest/download`
- Upstream source repository: `https://github.com/instrumentisto/grafana-dashboard-kubernetes-prometheus`
- Upstream license: MIT, vendored in `dashboard-315.LICENSE.txt`

Local normalization:

- Removed Grafana import-only `__inputs` metadata.
- Replaced `${DS_PROMETHEUS}` references with the checked-in Grafana datasource name `VictoriaMetrics` so the sidecar-provisioned dashboard loads without manual import prompts.
