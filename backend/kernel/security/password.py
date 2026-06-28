"""Password hashing using bcrypt (12 cost factor). Provider-agnostic — can be
swapped for argon2 / scrypt without changing call sites (ADR-013).
"""
from __future__ import annotations

import bcrypt

ROUNDS = 12


def hash_password(plaintext: str) -> str:
    if not isinstance(plaintext, str) or not plaintext:
        raise ValueError("password must be a non-empty string")
    salt = bcrypt.gensalt(rounds=ROUNDS)
    return bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    if not plaintext or not hashed:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
