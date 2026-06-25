"""Tenant context for structural multi-tenant isolation.

A `ContextVar` carries the **current request's tenant_id** through every async
call frame. All tenant-scoped data-access (`core.safe_db.tdb`) automatically
injects `{"tenant_id": current_tenant()}` into queries and stamps inserts.

Cross-tenant operations (admin, public, observer, regulator) MUST explicitly
opt out via the `bypass_tenant()` context manager — making intent visible in
code review and audit.
"""
from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import Optional

# None  → unauthenticated (public endpoints) or pre-auth phase
# str   → caller's tenant_id, queries auto-filtered to this tenant
_tenant_ctx: ContextVar[Optional[str]] = ContextVar("_tenant_ctx", default=None)

# True  → bypass tenant filtering for this scope (admin / observer / cross-tenant search)
_bypass_ctx: ContextVar[bool] = ContextVar("_bypass_ctx", default=False)


def set_tenant(tenant_id: Optional[str]) -> None:
    _tenant_ctx.set(tenant_id)


def current_tenant() -> Optional[str]:
    return _tenant_ctx.get()


def is_bypassed() -> bool:
    return _bypass_ctx.get()


@contextmanager
def bypass_tenant():
    """Synchronous context manager used by admin/cross-tenant code paths.

    Inside the `with bypass_tenant():` block, `tdb.<col>` will NOT auto-inject
    a tenant_id filter, allowing legitimate aggregated/admin reads.
    """
    tok = _bypass_ctx.set(True)
    try:
        yield
    finally:
        _bypass_ctx.reset(tok)


@asynccontextmanager
async def abypass_tenant():
    """Async-friendly alias for `bypass_tenant`."""
    tok = _bypass_ctx.set(True)
    try:
        yield
    finally:
        _bypass_ctx.reset(tok)
