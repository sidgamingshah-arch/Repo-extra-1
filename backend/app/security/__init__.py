"""Access control (RBAC) + session authentication."""
from __future__ import annotations

from .rbac import (
    PERMISSIONS,
    SCREENS_BY_ROLE,
    Permission,
    Principal,
    Role,
    current_principal,
    current_role,
    effective_permissions,
    has_permission,
    parse_role,
    permissions_for,
    require,
    screens_for,
)
from .session import (
    USERS,
    Session,
    User,
    authenticate,
    create_session,
    demo_users,
    destroy_session,
    resolve_session,
)

__all__ = [
    "PERMISSIONS", "SCREENS_BY_ROLE", "Permission", "Principal", "Role",
    "current_principal", "current_role", "effective_permissions", "has_permission",
    "parse_role", "permissions_for", "require", "screens_for",
    "USERS", "Session", "User", "authenticate", "create_session", "demo_users",
    "destroy_session", "resolve_session",
]
