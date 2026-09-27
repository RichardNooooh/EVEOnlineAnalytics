# Experiments

Exploratory notebooks provide supporting evidence for analytical decisions. Durable
transformations belong in dbt after an experiment establishes a stable rule.

## VS Code Notebooks

Sync the experiments environment from this directory:

```bash
uv sync
```

In VS Code, select `experiments/.venv/bin/python` as the notebook kernel. The
experiments project installs the local `transformation` package as an editable
dependency, so notebooks can use the shared read-only connection helper:

```python
from transform.notebook_access import open_analysis_connection

with open_analysis_connection() as connection:
    forge_history = connection.sql("""
        select *
        from main.int_forge_market_history
        limit 10
    """).df()
```

Run the dbt transformation build before querying its local relations. Close notebook
connections before rebuilding; the context manager closes the connection after each
`with` block. The default dbt work database remains
`/tmp/eve_market_transform.duckdb`, so notebook code does not change between builds.

The helper reads local catalog settings from `infra/local/.env` and honors the dbt
environment variables when present. It attaches raw DuckLake read-only and does not
create a durable database under `experiments/`.
