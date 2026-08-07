"""Authentication + identity endpoints.

* ``POST /auth/login``  — authenticate (username/password, or passwordless in demo
  mode) and receive a bearer session token.
* ``POST /auth/logout`` — invalidate the current session token.
* ``GET  /auth/demo-users`` — the seeded demo users (no secrets), for the login screen.
* ``GET  /me`` — the authenticated caller's role, permissions and visible screens
  (the frontend uses this to gate the nav and route access).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.config import get_settings
from app.security import (
    Principal,
    Role,
    authenticate,
    create_session,
    current_principal,
    demo_users,
    destroy_session,
    effective_permissions,
    screens_for,
)

router = APIRouter(tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str | None = None


def _user_payload(username: str, name: str, role: str) -> dict:
    return {"username": username, "name": name, "role": role}


@router.post("/auth/login")
def login(body: LoginBody) -> dict:
    settings = get_settings()
    user = authenticate(body.username, body.password, demo_mode=settings.auth.demo_mode)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    sess = create_session(user, settings.auth.session_ttl_minutes)
    return {
        "token": sess.token,
        "token_type": "bearer",
        "expires_in": settings.auth.session_ttl_minutes * 60,
        "user": _user_payload(user.username, user.name, user.role.value),
    }


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None)) -> dict:
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            destroy_session(token.strip())
    return {"ok": True}


@router.get("/auth/demo-users")
def list_demo_users() -> dict:
    """Public: seeded usernames/roles for the login screen's quick-login buttons."""
    settings = get_settings()
    return {"users": demo_users(), "demo_mode": settings.auth.demo_mode}


@router.get("/me")
def me(principal: Principal = Depends(current_principal)) -> dict:
    role = principal.role
    return {
        "authenticated": True,
        "username": principal.username,
        "name": principal.name,
        "via": principal.via,
        "role": role.value,
        "roles": [r.value for r in Role],
        "permissions": sorted(p.value for p in effective_permissions(role)),
        "screens": screens_for(role),
    }
