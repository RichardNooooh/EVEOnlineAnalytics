---
status: accepted
date: 2026-04-11
tags:
  - ingestion
  - everef
  - dlt
amended: []
---

# ADR-005 - Use a Custom Everef Ingestion Boundary

## Context

Everef market archives live at deterministic HTTPS paths such as:

`https://data.everef.net/market-history/{year}/market-history-{YYYY-MM-DD}.csv.bz2`

The project evaluated whether `dlt.sources.filesystem` could be the canonical discovery
mechanism for those archives. Exact known file paths work, but wildcard and recursive
HTTP discovery do not behave reliably enough for canonical acquisition.

Validation against the Everef market-history endpoint showed:

- exact known file access returned usable metadata through `dlt.sources.filesystem`
- year-level wildcard discovery surfaced files with `fsspec` metadata where `size=None`
- the current `dlt` filesystem wrapper then failed while constructing `size_in_bytes`
- recursive discovery from the endpoint root returned zero files

This is evidence for a broader source-boundary decision, not only a tooling limitation.
Everef ingestion also requires deterministic URL construction, explicit HTTP probe
metadata, endpoint-specific archive parsing, source-specific validation, handling late
archive revisions, and publication into DuckLake under the repository's single-writer
contract.

## Decision

Use a custom Everef ingestion boundary for archive acquisition and publication handoff.
Do not treat `dlt.sources.filesystem` wildcard or recursive HTTP listing as the canonical
Everef archive discovery mechanism.

The custom Everef boundary owns:

- endpoint definitions, date iteration, and deterministic URL construction
- explicit HTTP probe metadata such as status, `Content-Length`, `Last-Modified`, and `ETag`
- endpoint-specific parsing for compressed files and archives
- source-specific validation, missing-file policy, and late-revision detection
- handoff to DuckLake publication semantics for the relevant dataset scope

`dlt` may still be used where helpful for pipeline wiring and for other sources. This ADR
does not claim that Everef is incompatible with `dlt.sources.filesystem`; it states only
that wildcard and recursive HTTP discovery are not stable enough to be the canonical
Everef acquisition path.

Every custom abstraction must either represent an Everef-specific source concept or a
project-specific publication contract. Generic concerns should remain delegated to
established libraries.

## Consequences

### Positive

- Acquisition behavior matches the source's deterministic URL contract.
- Probe metadata can support skip logic, auditability, and late-revision handling.
- Archive parsing and validation stay close to Everef-specific semantics.
- The ingestion boundary stays aligned with DuckLake publication rules.

### Negative

- The project maintains source-specific acquisition and parsing code.
- More behavior must be tested in the custom ingestion package.

### Neutral

- Exact known Everef files remain accessible through standard HTTP tooling.
- This decision does not prohibit using `dlt` for ESI or for sources with reliable
  object-store-like discovery semantics.

## References

- `docs/architecture.md`
- `ingestion/ingest/sources/everef/client.py`
- `ingestion/ingest/sources/everef/market_history.py`
- `ingestion/ingest/archive/tarball.py`
- `ingestion/ingest/publishers/ducklake.py`
- https://dlthub.com/docs/dlt-ecosystem/verified-sources/filesystem
- https://filesystem-spec.readthedocs.io/en/latest/api.html
