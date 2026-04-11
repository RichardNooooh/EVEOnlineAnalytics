---
status: accepted
date: 2025-08-16
tags: 
  - data
amended: []
---

# ADR 001 - EVE Online Data Sources

## Context

The project requires historical and live EVE Online market data. Two primary public data sources exist:
[everef.net](https://everef.net), which archives historical market data, and the official EVE ESI (ESI) 
API, which provides live and recent market data per region and item type. No other authoritative sources 
exist for EVE market data at this fidelity.

## Decision

Use both sources in combination.

- **everef.net** is the source of truth for historical market data: daily market history CSVs (covering 
  the full game history) and order book snapshots captured twice per hour.
- **The EVE ESI API** is the source of truth for live and near-real-time data: market history by region/type
  and current order snapshots per region.
- **Primary region focus:** The Forge (`region_id: 10000002`), which contains the Jita trade hub - the 
  largest and most liquid market in EVE Online.

## Rationale

- everef.net provides a depth of historical coverage that the ESI API does not - the ESI's market history 
  endpoint returns up to 13 months of daily history per item, while everef.net archives data going back much 
  further. This historical depth is necessary to train ML models with enough examples of genuine anomalies 
  (price spikes, volume spikes, supply shocks, suspected manipulation).
- The ESI API is the authoritative source for current orders and recent history, and is necessary for the 
  operational (live) portion of the pipeline. everef.net's snapshots lag behind ESI by definition.
- Using both sources in parallel covers the full temporal range of the data product: historical batch loads 
  from everef.net, live/incremental loads from ESI.

**Known constraints and processing considerations:**

- **ESI rate limit:** 300 requests/minute. Ingestion scripts must implement rate limiting and backoff.
- **ESI `average` field bug:** The `average` field in ESI's market history response is actually a **median**, 
  not a mean. This is a confirmed bug documented in [esi-issues #451](https://github.com/esi/esi-issues/issues/451).
  The field is named `average` in the API response and must be aliased/documented internally to avoid misleading 
  downstream consumers and model features.
- **everef.net historical data validation:** The bulk CSV and JSON archives from everef.net require careful 
  validation on ingest. Records can be malformed or contain structurally invalid JSON (e.g., truncated files, 
  encoding issues, schema drift across archive epochs). A validation step - checking structural integrity, required 
  field presence, and type conformance before loading - is mandatory and must fail loudly on corrupt records rather 
  than silently skipping or coercing them. This is not optional hygiene; bad records propagating into the warehouse 
  corrupt feature engineering downstream.

## Alternatives considered

- *ESI only:* Would limit historical depth to ~13 months per item and miss the richer archive coverage needed for
  ML training. Not viable as a standalone source.
- *Third-party market sites (e.g., Janice, evemarketer):* These are consumer-facing tools, not data APIs. They do 
  not expose bulk historical data at the granularity required.

## Amendments

None.

