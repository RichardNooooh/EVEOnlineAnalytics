---
status: accepted
date: 2026-03-28
tags:
  - ml
amended: []
---

# ADR 006 - Classification Models over Regression for Market Analysis

## Context

The ML component needs to detect anomalous market behavior and predict price direction.
Both tasks could be framed as regression or classification problems.

## Decision

Both the primary model (market anomaly detection) and secondary model (price direction
prediction) use classification.

- **Anomaly classifier:** Binary normal vs. anomalous, with sub-classes: price spike,
  volume spike, suspected manipulation, supply shock.
- **Price direction classifier:** 3-class - up, down, flat.

## Rationale

- Classification produces clear evaluation metrics (precision, recall, F1, AUC-ROC) that
  are easier to communicate on a model card and in portfolio presentations than regression metrics (MAE, RMSE).
- Anomaly detection is naturally a classification problem. Framing price direction as classification
  (up/down/flat) rather than regression (predict exact price) better matches the use case - the dashboard
  consumer cares about directional signals, not point estimates.
