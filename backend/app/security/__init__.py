"""Access control (RBAC)."""
from __future__ import annotations

from .rbac import (
    PERMISSIONS,
    SCREENS_BY_ROLE,
    Permission,
    Role,
    current_role,
    has_permission,
    permissions_for,
    require,
)

__all__ = [
    "PERMISSIONS", "SCREENS_BY_ROLE", "Permission", "Role",
    "current_role", "has_permission", "permissions_for", "require",
]
