"""Identity API router — /api/v1/auth/*.

Routers in this codebase are composition only (ADR-007). They:
    1. parse + validate the request via DTOs
    2. enforce auth via PEP dependencies (where applicable)
    3. call AuthService
    4. shape the response and set the refresh cookie
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response

from contexts.identity.api.dtos import (
    LoginGoogleRequest,
    LoginLocalRequest,
    RegisterRequest,
    TokenResponse,
)
from contexts.identity.application.auth_service import AuthService
from kernel.audit import audit
from kernel.authorization import current_context_dep, require_auth
from kernel.config import SETTINGS
from kernel.persistence.context import ExecutionContext

logger = logging.getLogger("contexts.identity.api.auth")

router = APIRouter(prefix="/v1/auth", tags=["identity"])

_service: AuthService | None = None


def configure_router(service: AuthService) -> None:
    global _service
    _service = service


def _svc() -> AuthService:
    if _service is None:
        raise RuntimeError("AuthService not configured")
    return _service


def _set_refresh_cookie(response: Response, refresh_token: str, expires_at_iso: str) -> None:
    # The cookie spec allows max-age in seconds OR absolute expires; we use both.
    response.set_cookie(
        key=SETTINGS.refresh_cookie_name,
        value=refresh_token,
        httponly=True,
        secure=SETTINGS.cookie_secure,
        samesite=SETTINGS.cookie_samesite,
        max_age=SETTINGS.refresh_token_ttl_seconds,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(SETTINGS.refresh_cookie_name, path="/api/v1/auth")


def _client_meta(request: Request) -> tuple[Optional[str], Optional[str]]:
    fwd = request.headers.get("x-forwarded-for")
    ip = fwd.split(",", 1)[0].strip() if fwd else (request.client.host if request.client else None)
    return request.headers.get("user-agent"), ip


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, request: Request, response: Response,
                   _ctx: ExecutionContext = Depends(current_context_dep)) -> dict:
    svc = _svc()
    user = await svc.register_local(
        email=body.email, password=body.password, full_name=body.full_name,
        country=body.country,
    )
    ua, ip = _client_meta(request)
    tokens = await svc.login_local(email=user.email, password=body.password,
                                   user_agent=ua, ip=ip)
    _set_refresh_cookie(response, tokens["refresh_token"], tokens["refresh_expires_at"])
    return _token_response(tokens)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginLocalRequest, request: Request, response: Response,
                _ctx: ExecutionContext = Depends(current_context_dep)) -> dict:
    ua, ip = _client_meta(request)
    tokens = await _svc().login_local(email=body.email, password=body.password,
                                      user_agent=ua, ip=ip)
    _set_refresh_cookie(response, tokens["refresh_token"], tokens["refresh_expires_at"])
    return _token_response(tokens)


@router.post("/login/google", response_model=TokenResponse)
async def login_google(body: LoginGoogleRequest, request: Request, response: Response,
                       _ctx: ExecutionContext = Depends(current_context_dep)) -> dict:
    ua, ip = _client_meta(request)
    tokens = await _svc().login_emergent_google(session_id=body.session_id,
                                                user_agent=ua, ip=ip)
    _set_refresh_cookie(response, tokens["refresh_token"], tokens["refresh_expires_at"])
    return _token_response(tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response,
                  refresh_cookie: Optional[str] = Cookie(default=None,
                                                          alias=SETTINGS.refresh_cookie_name),
                  x_refresh_token: Optional[str] = Header(default=None)) -> dict:
    refresh_token = refresh_cookie or x_refresh_token
    ua, ip = _client_meta(request)
    tokens = await _svc().refresh(refresh_token=refresh_token or "", user_agent=ua, ip=ip)
    _set_refresh_cookie(response, tokens["refresh_token"], tokens["refresh_expires_at"])
    return _token_response(tokens)


@router.post("/logout", status_code=204)
async def logout(response: Response,
                 refresh_cookie: Optional[str] = Cookie(default=None,
                                                       alias=SETTINGS.refresh_cookie_name),
                 _ctx: ExecutionContext = Depends(current_context_dep)) -> Response:
    await _svc().logout(refresh_token=refresh_cookie)
    _clear_refresh_cookie(response)
    response.status_code = 204
    return response


@router.get("/me")
async def me(ctx: ExecutionContext = Depends(require_auth)) -> dict:
    await audit("identity.self.read", resource_type="user", resource_id=ctx.principal_id,
                decision="PERMIT")
    return {
        "user_id": ctx.principal_id,
        "email": ctx.email,
        "country": ctx.country,
        "tenant_id": ctx.tenant_id,
        "organization_id": ctx.organization_id,
        "roles": list(ctx.roles),
        "session_id": ctx.session_id,
    }


def _token_response(tokens: dict) -> dict:
    return {
        "access_token": tokens["access_token"],
        "token_type": tokens["token_type"],
        "expires_in": tokens["expires_in"],
        "user": tokens["user"],
    }
