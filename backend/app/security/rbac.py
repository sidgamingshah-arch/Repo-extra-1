"""Role-based access control.

Three roles with a permission matrix. Configuration actions (editing the template,
uploading an ontology, changing page scope, changing export inclusions, managing
documents) are **admin-controlled**; the analyst gets a deliberately simple flow
(view/edit values, notes, commentary, export). Reviewers sit in between.

Identity comes from a **session token** (``Authorization: Bearer …``) issued by
``POST /auth/login`` — see ``session.py``. For local dev, tests, and service-to-service
calls, an ``X-Role`` header is also accepted as an explicit credential, but only when
``auth.allow_role_header`` is enabled (config.toml) — turn it off in production so a
real session is the only way in. ``current_principal`` resolves the caller (401 if it
cannot); ``require()`` is a FastAPI dependency factory that returns 403 when the
resolved role lacks a permission.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from fastapi import Depends, Header, HTTPException, status


class Role(str, Enum):
    ADMIN = "admin"
    REVIEWER = "reviewer"
    ANALYST = "analyst"


class Permission(str, Enum):
    # configuration — admin-controlled
    CONFIG_TEMPLATE = "config:template"
    CONFIG_ONTOLOGY = "config:ontology"
    CONFIG_SCOPE = "config:scope"
    CONFIG_EXPORT = "config:export"
    CONFIG_SETTINGS = "config:settings"   # LLM / feature-flag / interface settings
    DOCUMENTS_MANAGE = "documents:manage"
    ADMIN_USERS = "admin:users"
    # working permissions
    EXTRACTION_VIEW = "extraction:view"
    EXTRACTION_EDIT = "extraction:edit"
    REVIEW_VIEW = "review:view"
    REVIEW_RESOLVE = "review:resolve"
    NOTES_VIEW = "notes:view"
    COMMENTARY_VIEW = "commentary:view"
    EXPORT_RUN = "export:run"
    INTEGRITY_VIEW = "integrity:view"


_ALL = set(Permission)

PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(_ALL),
    Role.REVIEWER: {
        Permission.EXTRACTION_VIEW, Permission.EXTRACTION_EDIT,
        Permission.REVIEW_VIEW, Permission.REVIEW_RESOLVE,
        Permission.NOTES_VIEW, Permission.COMMENTARY_VIEW,
        Permission.EXPORT_RUN, Permission.INTEGRITY_VIEW,
        Permission.CONFIG_SCOPE,  # reviewers may adjust page scope, not template/ontology
    },
    Role.ANALYST: {
        Permission.EXTRACTION_VIEW, Permission.EXTRACTION_EDIT,
        Permission.REVIEW_VIEW, Permission.NOTES_VIEW,
        Permission.COMMENTARY_VIEW, Permission.EXPORT_RUN,
        Permission.INTEGRITY_VIEW,
    },
}

# Which screens each role sees (drives the frontend nav; the analyst flow is lean).
SCREENS_BY_ROLE: dict[Role, list[str]] = {
    Role.ADMIN: ["upload", "integrity", "scope", "workspace", "notes", "review",
                 "commentary", "template", "settings", "export"],
    Role.REVIEWER: ["upload", "integrity", "scope", "workspace", "notes", "review",
                    "commentary", "export"],
    Role.ANALYST: ["workspace", "notes", "commentary", "export"],
}


def parse_role(value: str | None) -> Role:
    try:
        return Role(value) if value else Role.ANALYST
    except ValueError:
        return Role.ANALYST


@dataclass
class Principal:
    """The authenticated caller: their role plus who/how they authenticated."""

    role: Role
    username: str
    name: str
    via: str  # "session" | "role-header"


def current_principal(
    authorization: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> Principal:
    """Resolve the caller from a session token, or the X-Role dev header if allowed.

    Order: an explicit ``X-Role`` header wins (when ``auth.allow_role_header`` is on) so
    tooling/tests can act as any role; otherwise a valid ``Authorization: Bearer`` token
    is resolved to its session user. Raises 401 when neither yields a principal.
    """
    from app.config import get_settings

    from .session import resolve_session

    settings = get_settings()

    if x_role and settings.auth.allow_role_header:
        role = parse_role(x_role)
        return Principal(role=role, username=f"{role.value}@service",
                         name=f"{role.value.title()} (service)", via="role-header")

    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            sess = resolve_session(token.strip())
            if sess is not None:
                return Principal(role=sess.user.role, username=sess.user.username,
                                 name=sess.user.name, via="session")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def current_role(principal: Principal = Depends(current_principal)) -> Role:
    """FastAPI dependency: the authenticated caller's role."""
    return principal.role


def permissions_for(role: Role) -> set[Permission]:
    return PERMISSIONS.get(role, set())


def has_permission(role: Role, perm: Permission) -> bool:
    return perm in permissions_for(role)


def require(perm: Permission):
    """Dependency factory enforcing a permission; 403 if the role lacks it."""

    def _dep(role: Role = Depends(current_role)) -> Role:
        if not has_permission(role, perm):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {role.value!r} lacks permission {perm.value!r}",
            )
        return role

    return _dep
