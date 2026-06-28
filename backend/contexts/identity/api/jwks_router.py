"""JWKS endpoint — published public keys for token verification by federated
relying parties and future identity providers.

Spec: RFC 7517 / RFC 7518.
"""
from __future__ import annotations

from fastapi import APIRouter

from kernel.audit import audit
from kernel.security.keys import KeyStore

router = APIRouter(tags=["identity"])

_keystore: KeyStore | None = None


def configure_router(keystore: KeyStore) -> None:
    global _keystore
    _keystore = keystore


@router.get("/.well-known/jwks.json")
async def jwks() -> dict:
    if _keystore is None:
        return {"keys": []}
    await audit("identity.jwks.read", resource_type="signing_keys", decision="PERMIT")
    return await _keystore.public_jwks()
