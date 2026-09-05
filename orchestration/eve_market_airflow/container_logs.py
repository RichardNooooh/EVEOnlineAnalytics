from __future__ import annotations

import logging
import re
from typing import Any, Protocol

_LOG_LEVEL_PATTERN = re.compile(r"^(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b")
_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.CRITICAL,
}


class LogSink(Protocol):
    def info(self, msg: object, *args: object, **kwargs: object) -> None: ...

    def log(self, level: int, msg: object, *args: object, **kwargs: object) -> None: ...


class ContainerLogLevelRouter:
    """Restore child log levels flattened by DockerOperator.fetch_logs()."""

    def __init__(self, delegate: LogSink) -> None:
        self._delegate = delegate
        self.reset()

    def reset(self) -> None:
        self._inherited_level = logging.INFO

    def wraps(self, delegate: object) -> bool:
        return self._delegate is delegate

    def info(self, msg: object, *args: object, **kwargs: object) -> None:
        if msg != "%s" or len(args) != 1 or not isinstance(args[0], str):
            self._delegate.info(msg, *args, **kwargs)
            return

        match = _LOG_LEVEL_PATTERN.match(args[0])
        if match is not None:
            self._inherited_level = _LOG_LEVELS[match.group(1)]
        self._delegate.log(self._inherited_level, msg, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)
