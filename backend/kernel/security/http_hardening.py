"""Kernel — HTTP security hardening (R-2).

A single middleware that sets the production-grade security headers
on every response, plus a lightweight in-process rate limiter for
auth-sensitive routes.

Constitutional principle: security is a kernel concern, never a
domain concern. The middleware is configured once at startup and is
mechanically tested by ``tests/test_security_headers.py``.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import Callable, Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# ---- 1. Headers --------------------------------------------------------

# A *strict* CSP. The frontend is served from REACT_APP_BACKEND_URL
# only (same-origin via ingress). Inline scripts are forbidden; we
# rely on bundled CRA output. If the deployment introduces a CDN the
# CSP must be regenerated.
DEFAULT_CSP = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "  # Tailwind injects inline rules
    "script-src 'self'; "
    "connect-src 'self'; "
    "worker-src 'self' blob:; "
    "manifest-src 'self'; "
    "upgrade-insecure-requests"
)

DEFAULT_PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)


def _build_security_headers() -> dict[str, str]:
    """Return the production header set. Pinned, deterministic."""
    return {
        "Content-Security-Policy": os.environ.get("CSP_OVERRIDE", DEFAULT_CSP),
        "Strict-Transport-Security":
            "max-age=63072000; includeSubDomains; preload",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        # COEP is intentionally `require-corp` only on the API surface
        # — the React app does not need it because there's no shared
        # array buffer requirement. Setting it here would break iframe
        # embeds across tenants.
        "Cross-Origin-Embedder-Policy": "credentialless",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Permissions-Policy": DEFAULT_PERMISSIONS_POLICY,
    }


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Append the platform's security headers to every outgoing response.

    Idempotent: if a downstream handler has already set a header we
    don't override it.
    """

    def __init__(self, app):
        super().__init__(app)
        self._headers = _build_security_headers()

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        for k, v in self._headers.items():
            if k not in response.headers:
                response.headers[k] = v
        return response


# ---- 2. Rate limiter ---------------------------------------------------

# A pragmatic in-process sliding-window limiter. Per-pod, not
# distributed — production should front this with Cloudflare / ingress
# rate limiting at the edge. The middleware here is the *defence in
# depth* layer.

RATE_LIMITS: dict[str, tuple[int, int]] = {
    # path prefix → (max_requests, window_seconds)
    "/api/v1/auth/login": (10, 60),
    "/api/v1/auth/register": (5, 60),
    "/api/v1/auth/login/google": (10, 60),
    "/api/v1/evidence/items": (60, 60),
    "/api/v1/admin/projections": (20, 60),
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window per-IP rate limiter. 429 on overflow."""

    def __init__(self, app, *, enabled: bool = True):
        super().__init__(app)
        self._enabled = enabled
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _bucket(self, ip: str, path: str) -> tuple[int, int] | None:
        for prefix, lim in RATE_LIMITS.items():
            if path.startswith(prefix):
                return lim
        return None

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self._enabled:
            return await call_next(request)
        bucket = self._bucket(self._client_ip(request), request.url.path)
        if bucket is None:
            return await call_next(request)
        max_req, window = bucket
        key = f"{self._client_ip(request)}::{self._prefix_for(request.url.path)}"
        now = time.monotonic()
        dq = self._hits[key]
        # Drop expired hits.
        cutoff = now - window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= max_req:
            retry_after = int(window - (now - dq[0])) if dq else window
            return JSONResponse(
                status_code=429,
                content={
                    "type": "about:blank",
                    "title": "Too Many Requests",
                    "status": 429,
                    "code": "kernel.rate_limit",
                    "detail": (
                        f"Limit {max_req}/{window}s exceeded for "
                        f"{self._prefix_for(request.url.path)}"),
                },
                headers={"Retry-After": str(max(1, retry_after))},
            )
        dq.append(now)
        return await call_next(request)

    @staticmethod
    def _client_ip(request: Request) -> str:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    @staticmethod
    def _prefix_for(path: str) -> str:
        for prefix in RATE_LIMITS:
            if path.startswith(prefix):
                return prefix
        return path


def configure_security(app, *, rate_limit_enabled: bool = True) -> None:
    """Single-line attach used by ``backend/main.py`` at startup."""
    app.add_middleware(RateLimitMiddleware, enabled=rate_limit_enabled)
    app.add_middleware(SecurityHeadersMiddleware)


__all__ = [
    "SecurityHeadersMiddleware",
    "RateLimitMiddleware",
    "configure_security",
    "RATE_LIMITS",
    "DEFAULT_CSP",
    "DEFAULT_PERMISSIONS_POLICY",
]
