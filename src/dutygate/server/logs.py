"""JSON log formatting for the sidecar. Message text is never passed to a logger."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

EXTRA_FIELDS = ("request_id", "pack", "action", "error_code", "latency_ms", "status")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in EXTRA_FIELDS:
            if hasattr(record, key):
                data[key] = getattr(record, key)
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def log_config(level: str = "info") -> dict[str, Any]:
    """A logging.dictConfig for uvicorn and dutygate that writes one JSON object per line."""
    handler = {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stderr"}
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": f"{__name__}.JsonFormatter"}},
        "handlers": {"default": handler},
        "loggers": {
            "dutygate": {"handlers": ["default"], "level": level.upper(), "propagate": False},
            "uvicorn": {"handlers": ["default"], "level": level.upper(), "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": level.upper(), "propagate": False},
        },
    }
