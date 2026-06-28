"""Port: user persistence (Identity context).

The concrete adapter lives in `contexts.identity.adapters.mongo_user_repository`.
Application services depend on this port; swapping the database engine does
not affect the domain (ADR-013).
"""
from __future__ import annotations

from typing import Optional, Protocol

from contexts.identity.domain.user import User


class UserRepositoryPort(Protocol):
    async def get(self, user_id: str) -> Optional[User]: ...
    async def get_by_email(self, email: str) -> Optional[User]: ...
    async def add(self, user: User) -> User: ...
    async def update(self, user: User, expected_version: int) -> User: ...
    async def count(self) -> int: ...
