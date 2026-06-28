"""Make `/app` importable so `import contracts.generate` works from
the backend test suite (Phase 1C — Platform Contract Freeze).

This conftest is intentionally minimal — it only adjusts `sys.path` so
that the contract generator module, which lives at `/app/contracts/`,
is reachable from `pytest`. Production code is unaffected because it
already runs out of `/app/backend/` directly.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent.parent  # /app
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

# Auto-load /app/backend/.env so test invocations don't depend on shell setup.
# Production code already loads the .env via supervisor; this keeps pytest
# self-contained (notably for `kernel.config.settings` which reads MONGO_URL
# at import time).
_BACKEND_ENV = Path(__file__).resolve().parent.parent / ".env"
if _BACKEND_ENV.exists():
    for _line in _BACKEND_ENV.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        _k = _k.strip()
        _v = _v.strip().strip('"').strip("'")
        os.environ.setdefault(_k, _v)
