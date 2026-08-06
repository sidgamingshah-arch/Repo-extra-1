from __future__ import annotations

import os
import tempfile

import pytest

# Isolate the DB + object store per test session so nothing touches the dev workspace.
_tmp = tempfile.mkdtemp(prefix="finex-test-")
os.environ.setdefault("FINEX_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("FINEX_OBJECT_STORE_ROOT", f"{_tmp}/objects")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.db.base import init_db
    from app.main import app

    init_db()
    with TestClient(app) as c:
        yield c
