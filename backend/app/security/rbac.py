"""Role-based access control.

Three roles with a permission matrix. Configuration actions (editing the template,
uploading an ontology, changing page scope, changing export inclusions, managing
documents) are **admin-controlled**; the analyst gets a deliberately simple flow
(view/edit values, notes, commentary, export). Reviewers sit in between.

The current role is read from the ``X-Role`` request header (default ``analyst``) —
a pragmatic stand-in for real authentication, so the permission model and its
enforcement are real even though identity is not yet wired to an IdP. ``require()``
is a FastAPI dependency factory that returns 403 when the role lacks a permission.
"""
from __future__ import annotations

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
                 "commentary", "template", "export"],
    Role.REVIEWER: ["upload", "integrity", "scope", "workspace", "notes", "review",
                    "commentary", "export"],
    Role.ANALYST: ["workspace", "notes", "commentary", "export"],
}


def parse_role(value: str | None) -> Role:
    try:
        return Role(value) if value else Role.ANALYST
    except ValueError:
        return Role.ANALYST


def current_role(x_role: str | None = Header(default=None)) -> Role:
    """FastAPI dependency: resolve the caller's role from the X-Role header."""
    return parse_role(x_role)


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
