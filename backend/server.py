"""Backwards-compatible entrypoint.

Supervisor runs `uvicorn server:app` from /app/backend, so this module must
continue to expose `app`. The actual assembly lives in main.py.
"""
from main import app  # noqa: F401  — re-exported for uvicorn

__all__ = ["app"]
