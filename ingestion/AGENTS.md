# ingestion/AGENTS.md

This is a mostly hand-written rewrite attempt of the ingestion_old/ Python project.
User may ask for some help on portions of this project.

## Conventions
- When running any `python` commands, use `uv run` and working directory in `ingestion/`.

## dlt

`dlt` is declared as a dependency for future ESI endpoint ingestion. The current custom Python ingestion handles only everef.net bulk archives. Once ESI endpoints are implemented, they will use dlt for pipeline orchestration. dlt is not an unused or excess dependency.
