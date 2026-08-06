from __future__ import annotations

import os
import tempfile

import pytest

# Isolate the DB + object store per test session so nothing touches the dev workspace.
_tmp = tempfile.mkdtemp(prefix="finex-test-")
os.environ.setdefault("FINEX_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("FINEX_OBJECT_STORE_ROOT", f"{_tmp}/objects")


def _login_token(c, username: str) -> str:
    """Log in a seeded demo user (passwordless in demo mode) and return the token."""
    r = c.post("/api/v1/auth/login", json={"username": username})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def anon_client():
    """Unauthenticated client — for login flows and 401 assertions."""
    from fastapi.testclient import TestClient

    from app.db.base import init_db
    from app.main import app

    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def client(anon_client):
    """Authenticated client (admin session) — the default for most endpoint tests.

    Individual tests can still pass an explicit ``X-Role`` header to act as another
    role; that header takes precedence over this default admin token.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    token = _login_token(anon_client, "admin")
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c


@pytest.fixture(scope="session")
def auth(anon_client):
    """Return a helper yielding bearer-auth headers for a seeded demo user (cached)."""
    cache: dict[str, str] = {}

    def _headers(username: str) -> dict:
        if username not in cache:
            cache[username] = _login_token(anon_client, username)
        return {"Authorization": f"Bearer {cache[username]}"}

    return _headers
