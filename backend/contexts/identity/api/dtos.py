"""Identity DTOs (input/output schemas).

Unknown fields are rejected by Pydantic v2's `extra='forbid'` (binding API
standards §7: anti mass-assignment). Domain models are NEVER serialized
directly — every endpoint maps to/from these DTOs.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterRequest(_Strict):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    country: Optional[str] = Field(default=None, min_length=2, max_length=2)


class LoginLocalRequest(_Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class LoginGoogleRequest(_Strict):
    session_id: str = Field(min_length=10, max_length=512)


class TokenResponse(_Strict):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: dict
