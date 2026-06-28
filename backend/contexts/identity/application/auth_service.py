"""AuthService — Identity context's authentication use-cases.

Orchestrates:
    * Register (local provider only — social sign-ins register on first login)
    * Login (local + any external provider adapter)
    * Refresh (rotates refresh token, re-issues access token)
    * Logout (revokes the current session)

Returns DTO-shaped dicts so the API layer never sees domain types directly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from contexts.identity.adapters.mongo_session_repository import MongoSessionRepository
from contexts.identity.adapters.mongo_user_repository import MongoUserRepository
from contexts.identity.application.providers.emergent_google import (
    EmergentGoogleIdentityProvider,
)
from contexts.identity.application.providers.local import LocalIdentityProvider
from contexts.identity.domain.session import Session
from contexts.identity.domain.user import (
    ProviderIdentity,
    User,
)
from contexts.identity.domain.value_objects import (
    AccountStatus,
    CountryCode,
    Email,
    Role,
)
from contexts.identity.ports.identity_provider import IdentityProviderError
from kernel.audit import audit
from kernel.config import SETTINGS
from kernel.errors.problem import bad_request, conflict, unauthenticated
from kernel.events import new_envelope, publish
from kernel.observability.metrics import increment
from kernel.persistence.context import current_context
from kernel.security.jwt import JwtIssuer
from kernel.security.tokens import hash_token, new_opaque_token, refresh_expiry

logger = logging.getLogger("contexts.identity.auth")


class AuthService:
    def __init__(self, *, users: MongoUserRepository, sessions: MongoSessionRepository,
                 jwt_issuer: JwtIssuer) -> None:
        self.users = users
        self.sessions = sessions
        self.jwt_issuer = jwt_issuer
        self.local = LocalIdentityProvider()
        self.emergent_google = EmergentGoogleIdentityProvider()

    # ---- Registration ---------------------------------------------------
    async def register_local(self, *, email: str, password: str, full_name: str,
                             country: Optional[str] = None) -> User:
        try:
            normalized_email = Email.parse(email).value
        except ValueError as exc:
            raise bad_request(str(exc), code="auth.invalid_email") from exc
        if not password or len(password) < 8:
            raise bad_request("password must be at least 8 characters",
                              code="auth.weak_password")
        if not full_name or not full_name.strip():
            raise bad_request("full_name required", code="auth.missing_name")
        country_code = (country or SETTINGS.default_country).upper()
        try:
            country_code = CountryCode(country_code).value
        except ValueError as exc:
            raise bad_request(str(exc), code="auth.invalid_country") from exc

        if await self.users.get_by_email(normalized_email):
            raise conflict("Email already registered", code="identity.email_taken")

        user = User.new(email=normalized_email, full_name=full_name.strip(),
                        country=country_code,
                        role=Role.GENERAL_USER.value)
        user.add_identity(ProviderIdentity(
            provider="local", subject=normalized_email,
            password_hash=LocalIdentityProvider.hash(password),
        ))
        user = await self.users.add(user)
        await audit("identity.user.registered", resource_type="user",
                    resource_id=user.user_id,
                    payload={"provider": "local", "country": country_code})
        await publish(new_envelope(
            event_type="identity.user.registered", event_version=1,
            aggregate_type="user", aggregate_id=user.user_id,
            aggregate_version=user.version, producer="identity",
            payload={"provider": "local", "country": country_code,
                     "email": user.email, "role": user.role},
            tenant_id=user.tenant_id, country=user.country,
            organization_id=user.organization_id, actor=user.user_id,
        ))
        return user

    # ---- Login (local) --------------------------------------------------
    async def login_local(self, *, email: str, password: str, user_agent: Optional[str],
                          ip: Optional[str]) -> dict:
        normalized = Email.parse(email).value
        user = await self.users.get_by_email(normalized)
        if not user or not user.can_authenticate():
            await audit("identity.login.failed", resource_type="user",
                        decision="DENY",
                        payload={"provider": "local", "email": normalized,
                                 "reason": "user_not_found_or_inactive"})
            await increment("login_failed", labels={"provider": "local",
                                                    "reason": "not_found_or_inactive"})
            raise unauthenticated("Invalid email or password",
                                  code="auth.invalid_credentials")
        try:
            await self.local.verify(user, password)
        except IdentityProviderError as exc:
            await audit("identity.login.failed", resource_type="user",
                        resource_id=user.user_id, decision="DENY",
                        payload={"provider": "local", "reason": exc.code})
            await increment("login_failed", labels={"provider": "local",
                                                    "reason": exc.code})
            raise unauthenticated("Invalid email or password",
                                  code="auth.invalid_credentials") from exc
        return await self._issue_tokens(user, provider="local", user_agent=user_agent, ip=ip)

    # ---- Login (Emergent Google) ---------------------------------------
    async def login_emergent_google(self, *, session_id: str, user_agent: Optional[str],
                                    ip: Optional[str]) -> dict:
        try:
            subject = await self.emergent_google.authenticate({"session_id": session_id})
        except IdentityProviderError as exc:
            await audit("identity.login.failed", resource_type="user",
                        decision="DENY",
                        payload={"provider": "emergent_google", "reason": exc.code})
            raise unauthenticated("Could not verify Google sign-in",
                                  code=exc.code) from exc

        user = await self.users.get_by_provider_subject("emergent_google", subject.subject)
        if not user:
            user = await self.users.get_by_email(subject.email)
        if not user:
            # First-time sign-in via Google: provision a new canonical User.
            country_code = SETTINGS.default_country
            user = User.new(email=subject.email, full_name=subject.full_name or subject.email,
                            country=country_code, role=Role.GENERAL_USER.value)
            user.add_identity(ProviderIdentity(provider="emergent_google",
                                               subject=subject.subject,
                                               metadata=subject.metadata))
            user = await self.users.add(user)
            await audit("identity.user.registered", resource_type="user",
                        resource_id=user.user_id,
                        payload={"provider": "emergent_google", "country": country_code})
        elif not user.identity_for("emergent_google"):
            # Link Google to an existing local account on first Google sign-in.
            user.add_identity(ProviderIdentity(provider="emergent_google",
                                               subject=subject.subject,
                                               metadata=subject.metadata))
            user = await self.users.update(user, expected_version=user.version)
        return await self._issue_tokens(user, provider="emergent_google",
                                        user_agent=user_agent, ip=ip)

    # ---- Refresh --------------------------------------------------------
    async def refresh(self, *, refresh_token: str, user_agent: Optional[str],
                      ip: Optional[str]) -> dict:
        if not refresh_token:
            raise unauthenticated("Missing refresh token", code="auth.missing_refresh")
        rhash = hash_token(refresh_token)
        session = await self.sessions.get_by_refresh_hash(rhash)
        if not session:
            await audit("identity.refresh.unknown_token", resource_type="session",
                        decision="DENY")
            raise unauthenticated("Invalid refresh token",
                                  code="auth.invalid_refresh")
        if session.status != "ACTIVE":
            # Replay of a revoked or expired refresh token — kill ALL of the
            # user's active sessions as a token-theft heuristic.
            await self.sessions.revoke_user_sessions(session.user_id,
                                                    "refresh_token_replay")
            await audit("identity.refresh.replay_detected", resource_type="user",
                        resource_id=session.user_id, decision="DENY")
            raise unauthenticated("Refresh token reuse detected",
                                  code="auth.refresh_replay")
        if datetime.fromisoformat(session.expires_at) < datetime.now(timezone.utc):
            await self.sessions.revoke(session.session_id, "expired")
            raise unauthenticated("Refresh token expired", code="auth.refresh_expired")

        user = await self.users.get(session.user_id)
        if not user or not user.can_authenticate():
            await self.sessions.revoke(session.session_id, "user_inactive")
            raise unauthenticated("Account inactive", code="auth.account_inactive")

        # Rotate: revoke old, issue fresh.
        await self.sessions.revoke(session.session_id, "rotated")
        return await self._issue_tokens(user, provider="refresh",
                                        user_agent=user_agent, ip=ip,
                                        rotated_from=session.session_id)

    # ---- Logout ---------------------------------------------------------
    async def logout(self, *, refresh_token: Optional[str]) -> None:
        if not refresh_token:
            return
        session = await self.sessions.get_by_refresh_hash(hash_token(refresh_token))
        if session and session.status == "ACTIVE":
            await self.sessions.revoke(session.session_id, "user_logout")
            await audit("identity.logout", resource_type="session",
                        resource_id=session.session_id)
            await publish(new_envelope(
                event_type="identity.session.revoked", event_version=1,
                aggregate_type="session", aggregate_id=session.session_id,
                aggregate_version=session.version, producer="identity",
                payload={"reason": "user_logout", "user_id": session.user_id},
                actor=session.user_id,
            ))
            await increment("revoked_sessions", labels={"reason": "logout"})

    # ---- Internal: token minting ---------------------------------------
    async def _issue_tokens(self, user: User, *, provider: str, user_agent: Optional[str],
                            ip: Optional[str], rotated_from: Optional[str] = None) -> dict:
        # Create the session BEFORE the access token so `sid` can be embedded.
        plaintext_refresh, rhash = new_opaque_token()
        expires_at = refresh_expiry().isoformat()
        session = Session.new(
            user_id=user.user_id, refresh_token_hash=rhash, expires_at=expires_at,
            user_agent=user_agent, ip_address=ip, rotated_from=rotated_from,
        )
        await self.sessions.add(session)
        access_token, claims = await self.jwt_issuer.issue_access(
            subject=user.user_id,
            email=user.email,
            country=user.country,
            tenant_id=user.tenant_id,
            organization_id=user.organization_id,
            roles=list(user.roles),
            attributes={"country": user.country, "tenant_id": user.tenant_id,
                        "sid": session.session_id},
        )
        user.mark_logged_in()
        try:
            user = await self.users.update(user, expected_version=user.version)
        except Exception:  # noqa: BLE001 — last_login is best-effort
            logger.warning("could not stamp last_login_at for %s", user.user_id)

        await audit("identity.login.success", resource_type="user",
                    resource_id=user.user_id, decision="PERMIT",
                    payload={"provider": provider, "session_id": session.session_id,
                             "rotated_from": rotated_from})
        await publish(new_envelope(
            event_type="identity.login.success", event_version=1,
            aggregate_type="session", aggregate_id=session.session_id,
            aggregate_version=session.version, producer="identity",
            payload={"user_id": user.user_id, "provider": provider,
                     "rotated_from": rotated_from},
            tenant_id=user.tenant_id, country=user.country,
            organization_id=user.organization_id, actor=user.user_id,
        ))
        await increment("login_success", labels={"provider": provider,
                                                 "country": user.country})
        await increment("active_sessions")
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": SETTINGS.access_token_ttl_seconds,
            "refresh_token": plaintext_refresh,
            "refresh_expires_at": expires_at,
            "session_id": session.session_id,
            "user": user.public_view(),
            "claims": {k: claims[k] for k in
                       ("sub", "iss", "aud", "exp", "iat", "jti", "country", "tenant_id")},
        }
