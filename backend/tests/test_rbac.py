"""RBAC + session auth: login, role→permission enforcement, and /me."""
from __future__ import annotations


def test_me_requires_authentication(anon_client):
    # No session token and no role header → 401.
    assert anon_client.get("/api/v1/me").status_code == 401


def test_login_issues_token_and_scopes_analyst(anon_client):
    r = anon_client.post("/api/v1/auth/login", json={"username": "analyst"})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    assert r.json()["user"]["role"] == "analyst"

    me = anon_client.get("/api/v1/me", headers={"Authorization": f"Bearer {tok}"}).json()
    assert me["authenticated"] is True and me["role"] == "analyst" and me["via"] == "session"
    assert "workspace" in me["screens"] and "commentary" in me["screens"]
    assert "template" not in me["screens"] and "settings" not in me["screens"]
    assert "config:template" not in me["permissions"]


def test_login_rejects_bad_password(anon_client):
    # A wrong (non-empty) password is rejected even in demo mode.
    r = anon_client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_logout_invalidates_token(anon_client):
    tok = anon_client.post("/api/v1/auth/login", json={"username": "reviewer"}).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    assert anon_client.get("/api/v1/me", headers=hdr).status_code == 200
    anon_client.post("/api/v1/auth/logout", headers=hdr)
    assert anon_client.get("/api/v1/me", headers=hdr).status_code == 401


def test_me_admin_sees_config(client):
    me = client.get("/api/v1/me", headers={"X-Role": "admin"}).json()
    assert me["role"] == "admin"
    assert "template" in me["screens"] and "settings" in me["screens"]
    assert "config:template" in me["permissions"] and "config:settings" in me["permissions"]


def test_reviewer_scope_but_not_template(client):
    me = client.get("/api/v1/me", headers={"X-Role": "reviewer"}).json()
    assert "review" in me["screens"] and "template" not in me["screens"]
    assert "config:scope" in me["permissions"]
    assert "config:template" not in me["permissions"]


def test_demo_users_listed_without_secrets(anon_client):
    body = anon_client.get("/api/v1/auth/demo-users").json()
    roles = {u["role"] for u in body["users"]}
    assert roles == {"admin", "reviewer", "analyst"}
    assert all("password" not in u for u in body["users"])


def test_template_config_requires_admin(client, anon_client):
    # Unauthenticated → 401; reviewer → 403; admin → 200.
    assert anon_client.get("/api/v1/projects/demo/template").status_code == 401
    assert client.get("/api/v1/projects/demo/template", headers={"X-Role": "reviewer"}).status_code == 403
    assert client.get("/api/v1/projects/demo/template", headers={"X-Role": "admin"}).status_code == 200

    tpl = {"template_key": "rbac_t", "name": "T", "statements": []}
    assert anon_client.post("/api/v1/templates", json={"definition": tpl}).status_code == 401
    assert client.post("/api/v1/templates", json={"definition": tpl},
                       headers={"X-Role": "admin"}).status_code == 201


def test_edit_allowed_for_working_roles(client):
    # analyst may edit values (simple flow); the mutation is permitted.
    r = client.patch("/api/v1/projects/demo/line-items/ppe",
                     json={"value": 423180, "formula": ""}, headers={"X-Role": "analyst"})
    assert r.status_code == 200
    client.delete("/api/v1/projects/demo/line-items/ppe", headers={"X-Role": "analyst"})


def test_role_header_ignored_when_disabled(anon_client, monkeypatch):
    # With allow_role_header off, the X-Role dev header is not accepted → 401.
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s.auth, "allow_role_header", False)
    assert anon_client.get("/api/v1/me", headers={"X-Role": "admin"}).status_code == 401
