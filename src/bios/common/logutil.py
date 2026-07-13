"""Structured logging setup.

Standard-library logging with an optional JSON formatter — no logging
framework dependency (Constitution Art.8). Application code obtains
loggers via :func:`get_logger` and passes context through ``extra``.

Operational logs (this module) and the audit log (bios.audit) are distinct:
logs are for humans debugging, audit records are load-bearing data.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line; ``extra`` kwargs become top-level keys."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO", json_lines: bool = False) -> None:
    """Configure the root logger once at process start (idempotent)."""
    handler = logging.StreamHandler(sys.stderr)
    if json_lines:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    """Namespaced logger; ``name`` should be the module's ``__name__``."""
    return logging.getLogger(name)
