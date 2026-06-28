"""Observability primitives: structured logs, correlation id propagation."""
import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Optional

correlation_id_ctx: ContextVar[Optional[str]] = ContextVar("correlation_id_ctx", default=None)


def current_correlation_id() -> Optional[str]:
    return correlation_id_ctx.get()


def set_correlation_id(value: Optional[str] = None) -> str:
    cid = value or str(uuid.uuid4())
    correlation_id_ctx.set(cid)
    return cid


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter — no PII in logs (binding, Infrastructure §9)."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": current_correlation_id(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
