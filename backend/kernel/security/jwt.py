"""JWT issuance and verification (RS256, kid-rotated).

Claims policy:
    iss   = SETTINGS.jwt_issuer
    aud   = SETTINGS.jwt_audience
    sub   = principal_id (user_id)
    iat / nbf / exp  = standard
    jti   = unique token id (for blacklisting / refresh-rotation)
    typ   = "access" | "refresh"     (refresh tokens are opaque, not JWTs — see tokens.py)
    email                            (string, normalized lowercase)
    country                          (ISO 3166-1 alpha-2, required)
    tenant_id                        (string or null for platform-level service principals)
    organization_id                  (string or null)
    roles                            (list[str], RBAC)
    attributes                       (dict[str, str], ABAC — country, tenant repeated for convenience)

Only the Identity context creates these tokens; everything else verifies.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt as pyjwt
from jwt import InvalidTokenError

from kernel.config import SETTINGS
from kernel.security.keys import KeyStore

logger = logging.getLogger("kernel.security.jwt")
ALG = "RS256"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JwtIssuer:
    def __init__(self, keystore: KeyStore) -> None:
        self.keystore = keystore

    async def issue_access(self, *, subject: str, email: str, country: str,
                           tenant_id: Optional[str], organization_id: Optional[str],
                           roles: list[str], attributes: dict[str, Any]) -> tuple[str, dict]:
        key = await self.keystore.get_signing_key()
        now = _now()
        exp = now + timedelta(seconds=SETTINGS.access_token_ttl_seconds)
        claims = {
            "iss": SETTINGS.jwt_issuer,
            "aud": SETTINGS.jwt_audience,
            "sub": subject,
            "jti": uuid.uuid4().hex,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "typ": "access",
            "email": email,
            "country": country,
            "tenant_id": tenant_id,
            "organization_id": organization_id,
            "roles": roles,
            "attributes": attributes,
        }
        token = pyjwt.encode(claims, key["pem_private"], algorithm=ALG, headers={"kid": key["kid"]})
        return token, claims


class JwtVerifier:
    def __init__(self, keystore: KeyStore) -> None:
        self.keystore = keystore

    async def verify(self, token: str) -> dict:
        """Return verified claims dict, or raise InvalidTokenError."""
        try:
            unverified_header = pyjwt.get_unverified_header(token)
        except Exception as exc:
            raise InvalidTokenError("unparseable token header") from exc

        kid = unverified_header.get("kid")
        if not kid:
            raise InvalidTokenError("missing kid")

        key = await self.keystore.get_verify_key(kid)
        if not key:
            raise InvalidTokenError(f"unknown kid {kid}")

        claims = pyjwt.decode(
            token,
            key["pem_public"],
            algorithms=[ALG],
            audience=SETTINGS.jwt_audience,
            issuer=SETTINGS.jwt_issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        return claims
