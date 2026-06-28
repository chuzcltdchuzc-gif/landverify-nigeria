"""Local email + password identity provider.

Credentials: `{ "email": "...", "password": "..." }`.
Authenticates by looking up the user's local provider identity and verifying
the password hash. Note: lookup itself is not the provider's responsibility —
authentication is. The provider only verifies the password against an
already-loaded hash (the AuthService loads the user first).
"""
from __future__ import annotations

from contexts.identity.domain.user import User
from contexts.identity.ports.identity_provider import (
    AuthenticatedSubject,
    IdentityProviderError,
)
from kernel.security.password import verify_password


class LocalIdentityProvider:
    """Verifies a (email, password) pair against a User's local identity."""

    name = "local"

    async def verify(self, user: User, password: str) -> AuthenticatedSubject:
        ident = user.identity_for("local")
        if not ident or not ident.password_hash:
            raise IdentityProviderError("No local credential on file",
                                        code="auth.no_local_credential")
        if not verify_password(password, ident.password_hash):
            raise IdentityProviderError("Invalid email or password",
                                        code="auth.invalid_credentials")
        return AuthenticatedSubject(
            provider="local",
            subject=user.email,
            email=user.email,
            full_name=user.full_name,
        )

    @staticmethod
    def hash(password: str) -> str:
        from kernel.security.password import hash_password
        return hash_password(password)
