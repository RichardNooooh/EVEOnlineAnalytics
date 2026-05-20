# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.11.14-python3.13-trixie-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HOME=/app \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

ARG APP_UID=10001
ARG APP_GID=10001

RUN groupadd --system --gid "${APP_GID}" app \
    && useradd --system \
        --uid "${APP_UID}" \
        --gid app \
        --home-dir /app \
        --shell /usr/sbin/nologin \
        app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --no-editable

COPY README.md ./
COPY ingest ./ingest
COPY main.py ./main.py

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable \
    && mkdir -p /app/.local /app/.dlt /opt/eve-market/data \
    && chown -R app:app /app /opt/eve-market/data

USER app

ENTRYPOINT ["eve-ingest"]
CMD ["--help"]
