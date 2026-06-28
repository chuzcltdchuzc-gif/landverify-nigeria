"""Security primitives — JWT issuance/verification, JWKS, password hashing.

All cryptographic operations live here so they can be rotated or replaced
without touching higher layers (ADR-013).
"""
