"""Emergent-Managed Google Auth — adapter wrapping the existing
Emergent OAuth session-exchange endpoint behind the IdentityProvider port.

Credentials: `{ "session_id": "<sid_from_emergent>" }`.
On success returns an `AuthenticatedSubject` populated from the Emergent
profile (email, name, picture). The Identity context then maps this to a
canonical User (creating one on first sign-in).

This is an Anti-Corruption Layer (Foundation Spec §13): the external profile
shape never enters the domain — only the typed `AuthenticatedSubject` does.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from contexts.identity.ports.identity_provider import (
    AuthenticatedSubject,
    IdentityProviderError,
)

logger = logging.getLogger("contexts.identity.providers.emergent_google")

DEFAULT_EMERGENT_SESSION_URL = os.environ.get(
    "EMERGENT_SESSION_URL",
    "https://auth.emergentagent.com/api/auth/v1/session",
)


class EmergentGoogleIdentityProvider:
    name = "emergent_google"

    def __init__(self, session_url: Optional[str] = None,
                 timeout_seconds: float = 10.0) -> None:
        self.session_url = session_url or DEFAULT_EMERGENT_SESSION_URL
        self.timeout = timeout_seconds

    async def authenticate(self, credentials: dict) -> AuthenticatedSubject:
        session_id = (credentials or {}).get("session_id")
        if not session_id:
            raise IdentityProviderError("session_id required",
                                        code="auth.missing_session_id")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(self.session_url,
                                        headers={"X-Session-ID": session_id})
        except httpx.HTTPError as exc:
            logger.warning("emergent session exchange failed: %s", exc)
            raise IdentityProviderError("Emergent auth unreachable",
                                        code="auth.provider_unreachable") from exc
        if resp.status_code != 200:
            raise IdentityProviderError("Invalid Emergent session",
                                        code="auth.invalid_session")
        body = resp.json()
        email = (body.get("email") or "").lower().strip()
        if not email:
            raise IdentityProviderError("Emergent did not return an email",
                                        code="auth.no_email")
        return AuthenticatedSubject(
            provider="emergent_google",
            subject=str(body.get("id") or email),
            email=email,
            full_name=body.get("name") or "",
            metadata={k: v for k, v in body.items() if k in {"picture"}},
        )
