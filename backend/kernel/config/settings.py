"""Platform-wide typed configuration (loaded once at startup, fail-fast).

Reads from environment variables only — never from request content. Default
operational country is NG; the architecture itself does not assume Nigeria
(Country is a first-class scope dimension throughout the Kernel).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformSettings:
    # ---- Identity / JWT --------------------------------------------------
    jwt_issuer: str
    jwt_audience: str
    access_token_ttl_seconds: int
    refresh_token_ttl_seconds: int
    key_rotation_grace_seconds: int

    # ---- Country (first-class scoping dimension) -------------------------
    default_country: str

    # ---- Cookies ---------------------------------------------------------
    refresh_cookie_name: str
    cookie_secure: bool
    cookie_samesite: str  # "lax" | "strict" | "none"

    # ---- Database --------------------------------------------------------
    mongo_url: str
    db_name: str


def load_settings() -> PlatformSettings:
    def _i(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, str(default)))
        except ValueError:
            return default

    def _b(name: str, default: bool) -> bool:
        v = os.environ.get(name, "true" if default else "false").strip().lower()
        return v in ("1", "true", "yes", "on")

    return PlatformSettings(
        jwt_issuer=os.environ.get("PLATFORM_JWT_ISSUER", "https://aquasavannah.landvault"),
        jwt_audience=os.environ.get("PLATFORM_JWT_AUDIENCE", "landvault-api"),
        access_token_ttl_seconds=_i("PLATFORM_ACCESS_TTL_SECONDS", 900),       # 15 min
        refresh_token_ttl_seconds=_i("PLATFORM_REFRESH_TTL_SECONDS", 2592000),  # 30 days
        key_rotation_grace_seconds=_i("PLATFORM_KEY_GRACE_SECONDS", 86400),    # 1 day overlap
        default_country=os.environ.get("PLATFORM_DEFAULT_COUNTRY", "NG").upper(),
        refresh_cookie_name=os.environ.get("PLATFORM_REFRESH_COOKIE", "lv_refresh"),
        cookie_secure=_b("PLATFORM_COOKIE_SECURE", True),
        cookie_samesite=os.environ.get("PLATFORM_COOKIE_SAMESITE", "none"),
        mongo_url=os.environ["MONGO_URL"],
        db_name=os.environ.get("DB_NAME", "test_database"),
    )


SETTINGS: PlatformSettings = load_settings()
