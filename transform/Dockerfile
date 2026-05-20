# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.11.14-python3.13-trixie-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HOME=/app \
    DBT_PROFILES_DIR=/app \
    DBT_PROJECT_DIR=/app \
    DBT_DUCKDB_PATH=/tmp/eve_market_transform.duckdb \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

ARG APP_UID=10001
ARG APP_GID=10001

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid "${APP_GID}" app \
    && useradd --system \
        --uid "${APP_UID}" \
        --gid app \
        --home-dir /app \
        --shell /usr/sbin/nologin \
        app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY README.md ./
COPY dbt_project.yml ./
COPY profiles.yml ./
COPY analyses ./analyses
COPY macros ./macros
COPY models ./models
COPY seeds ./seeds
COPY tests ./tests

RUN mkdir -p /app/.dbt /tmp \
    && chown -R app:app /app /tmp

USER app

ENTRYPOINT ["dbt"]
CMD ["--help"]
