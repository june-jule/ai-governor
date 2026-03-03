"""Structured JSON logging for Governor.

Opt-in: import and call ``configure_logging()`` to activate.
Does NOT auto-activate on import.

Usage::

    from governor.logging import configure_logging, StructuredLogger

    configure_logging(level="DEBUG")
    log = StructuredLogger("governor.engine")
    log.info("transition started", task_id="TASK_001", guard_id="EG-01")
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class StructuredFormatter(logging.Formatter):
    """Formats each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge any extra fields passed via `extra={"ctx": {...}}`
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            entry.update(ctx)
        return json.dumps(entry, default=str)


class StructuredLogger:
    """Thin wrapper around ``logging.Logger`` that injects context fields."""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _log(self, level: int, msg: str, kwargs: dict[str, Any]) -> None:
        exc_info = kwargs.pop("exc_info", False)
        self._logger.log(level, msg, extra={"ctx": kwargs}, exc_info=exc_info)

    def debug(self, msg: str, **kw: Any) -> None:
        self._log(logging.DEBUG, msg, kw)

    def info(self, msg: str, **kw: Any) -> None:
        self._log(logging.INFO, msg, kw)

    def warning(self, msg: str, **kw: Any) -> None:
        self._log(logging.WARNING, msg, kw)

    def error(self, msg: str, **kw: Any) -> None:
        self._log(logging.ERROR, msg, kw)

    def critical(self, msg: str, **kw: Any) -> None:
        self._log(logging.CRITICAL, msg, kw)


def configure_logging(
    level: str = "INFO",
    stream: Optional[Any] = None,
) -> None:
    """Activate structured JSON logging on the ``governor`` hierarchy."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(StructuredFormatter())
    root = logging.getLogger("governor")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logging_config(level: str = "INFO") -> Dict[str, Any]:
    """Return a ``logging.config.dictConfig``-compatible configuration dict.

    Usage::

        import logging.config
        from governor.logging import get_logging_config

        logging.config.dictConfig(get_logging_config(level="DEBUG"))
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "governor_structured": {
                "()": "governor.logging.StructuredFormatter",
            },
        },
        "handlers": {
            "governor_stderr": {
                "class": "logging.StreamHandler",
                "formatter": "governor_structured",
                "stream": "ext://sys.stderr",
            },
        },
        "loggers": {
            "governor": {
                "level": level.upper(),
                "handlers": ["governor_stderr"],
                "propagate": False,
            },
        },
    }
