from __future__ import annotations

import logging
import logging.config
import os
from pathlib import Path
from typing import Final

import yaml

DEFAULT_LOG_LEVEL: Final[str] = "INFO"
_INVALID_LEVEL_WARNING = "Invalid INGEST_LOG_LEVEL=%r; falling back to %s"
_RUNTIME_CONTEXT_ENV_VARS: Final[dict[str, str]] = {
    "dag_id": "AIRFLOW_CTX_DAG_ID",
    "task_id": "AIRFLOW_CTX_TASK_ID",
    "run_id": "AIRFLOW_CTX_RUN_ID",
    "try_number": "AIRFLOW_CTX_TRY_NUMBER",
}
_CONFIG_PATH = Path(__file__).with_name("logging_configs") / "config.yaml"

_configured = False
logger = logging.getLogger("ingest")


def configure_logging(*, force: bool = False) -> None:
    global _configured

    if _configured and not force:
        return

    level_name, invalid_level = _resolve_log_level_name()
    logging.config.dictConfig(_load_logging_config(level_name))
    _configured = True

    if invalid_level is not None:
        logger.warning(
            _INVALID_LEVEL_WARNING,
            invalid_level,
            DEFAULT_LOG_LEVEL,
        )


def log_runtime_context() -> None:
    context = {name: os.environ.get(env_var) for name, env_var in _RUNTIME_CONTEXT_ENV_VARS.items()}
    context = {name: value for name, value in context.items() if value}
    if not context:
        return

    context_fields = " ".join(f"{name}={value}" for name, value in context.items())
    logger.info("runtime_context %s", context_fields)


def _resolve_log_level_name() -> tuple[str, str | None]:
    raw_level = os.environ.get("INGEST_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper()
    valid_levels = logging.getLevelNamesMapping()
    if raw_level in valid_levels:
        return raw_level, None
    return DEFAULT_LOG_LEVEL, raw_level


def _load_logging_config(level_name: str) -> dict[str, object]:
    with _CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    ingest_logger = config.setdefault("loggers", {}).setdefault("ingest", {})
    ingest_logger["level"] = level_name
    return config
