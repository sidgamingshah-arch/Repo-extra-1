"""Identity / access endpoints. GET /me reports the caller's role, permissions, and
the screens their role may see (the frontend uses this to filter the nav)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.security import (
    SCREENS_BY_ROLE,
    Role,
    current_role,
    permissions_for,
)

router = APIRouter(tags=["auth"])


@router.get("/me")
def me(role: Role = Depends(current_role)) -> dict:
    return {
        "role": role.value,
        "roles": [r.value for r in Role],
        "permissions": sorted(p.value for p in permissions_for(role)),
        "screens": SCREENS_BY_ROLE.get(role, []),
    }
