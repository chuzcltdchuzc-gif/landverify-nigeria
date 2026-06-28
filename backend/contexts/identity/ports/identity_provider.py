"""Identity Provider port — every external authentication provider implements
this interface and is registered under a name (e.g. 'local', 'emergent_google').

A provider's job is narrow: given a `credentials` payload, return an
`AuthenticatedSubject` (provider id + subject id + verified email + display
name + metadata) or raise. The Identity Context then maps the subject to a
canonical `User`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass(frozen=True)
class AuthenticatedSubject:
    provider: str               # "local" | "emergent_google" | future
    subject: str                # provider-specific id (OAuth `sub` or local email lower)
    email: str                  # verified email, lowercase
    full_name: str = ""
    metadata: dict = field(default_factory=dict)


class IdentityProviderPort(Protocol):
    @property
    def name(self) -> str: ...

    async def authenticate(self, credentials: dict) -> AuthenticatedSubject: ...


class IdentityProviderError(Exception):
    """Raised by any provider when authentication fails."""

    def __init__(self, message: str, *, code: str = "auth.provider_failed",
                 detail: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail
