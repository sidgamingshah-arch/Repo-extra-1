"""API dependencies."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.base import get_session
from app.ports.object_store import LocalObjectStore


def db() -> Iterator[Session]:
    yield from get_session()


def settings() -> Settings:
    return get_settings()


def object_store() -> LocalObjectStore:
    return LocalObjectStore(get_settings().object_store_root)
