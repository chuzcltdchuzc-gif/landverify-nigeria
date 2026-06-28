"""RSA signing key generation, rotation, and JWKS publication.

Keys are persisted in MongoDB collection `kernel_signing_keys`. Each key has a
unique `kid`. Rotation policy:
* At most one ACTIVE signing key at a time. New tokens are always signed with it.
* Previously-active keys remain VERIFY_ONLY for `key_rotation_grace_seconds`,
  so tokens issued before rotation continue to verify until they expire.
* Retired keys are kept indefinitely for forensic audit (append-only intent)
  but excluded from the public JWKS once retired.

This module never logs private key material.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from kernel.config import SETTINGS

logger = logging.getLogger("kernel.security.keys")

KEY_SIZE_BITS = 2048
COLLECTION = "kernel_signing_keys"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _int_to_b64url(value: int) -> str:
    length = (value.bit_length() + 7) // 8
    return _b64url(value.to_bytes(length, "big"))


def _generate_keypair() -> tuple[str, str]:
    """Return (pem_private, pem_public) for a fresh 2048-bit RSA key."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE_BITS)
    pem_private = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pem_public = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return pem_private, pem_public


def _load_public(pem: str) -> RSAPublicKey:
    return serialization.load_pem_public_key(pem.encode())  # type: ignore[return-value]


def _load_private(pem: str) -> RSAPrivateKey:
    return serialization.load_pem_private_key(pem.encode(), password=None)  # type: ignore[return-value]


def public_jwk(kid: str, pem_public: str) -> dict:
    pub = _load_public(pem_public)
    numbers = pub.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _int_to_b64url(numbers.n),
        "e": _int_to_b64url(numbers.e),
    }


class KeyStore:
    """MongoDB-backed signing-key store. Used by the JWT issuer + JWKS endpoint."""

    def __init__(self, db) -> None:
        self.db = db
        self.collection = db[COLLECTION]

    async def ensure_active_key(self) -> dict:
        """Return the current ACTIVE key, generating one if none exists."""
        existing = await self.collection.find_one({"status": "ACTIVE"}, {"_id": 0})
        if existing:
            return existing
        return await self.rotate()

    async def rotate(self) -> dict:
        """Generate a new ACTIVE key and demote the prior one to VERIFY_ONLY."""
        now = _now()
        grace = SETTINGS.key_rotation_grace_seconds
        retire_at = now + timedelta(seconds=grace)

        await self.collection.update_many(
            {"status": "ACTIVE"},
            {"$set": {"status": "VERIFY_ONLY", "retired_at": now.isoformat(),
                      "valid_until": retire_at.isoformat()}},
        )
        # purge fully-expired keys from JWKS but keep them for audit
        await self.collection.update_many(
            {"status": "VERIFY_ONLY", "valid_until": {"$lt": now.isoformat()}},
            {"$set": {"status": "RETIRED"}},
        )

        kid = f"kid_{int(now.timestamp())}"
        pem_private, pem_public = _generate_keypair()
        doc = {
            "kid": kid,
            "status": "ACTIVE",
            "alg": "RS256",
            "created_at": now.isoformat(),
            "pem_private": pem_private,
            "pem_public": pem_public,
        }
        await self.collection.insert_one(dict(doc))
        logger.info("signing key rotated: new kid=%s", kid)
        return doc

    async def get_signing_key(self) -> dict:
        key = await self.collection.find_one({"status": "ACTIVE"}, {"_id": 0})
        if not key:
            key = await self.ensure_active_key()
        return key

    async def get_verify_key(self, kid: str) -> Optional[dict]:
        return await self.collection.find_one(
            {"kid": kid, "status": {"$in": ["ACTIVE", "VERIFY_ONLY"]}}, {"_id": 0},
        )

    async def public_jwks(self) -> dict:
        keys: list[dict] = []
        cur = self.collection.find({"status": {"$in": ["ACTIVE", "VERIFY_ONLY"]}}, {"_id": 0})
        async for k in cur:
            keys.append(public_jwk(k["kid"], k["pem_public"]))
        return {"keys": keys}
