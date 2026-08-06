"""RBAC: role→permission enforcement and /me."""
from __future__ import annotations


def test_me_defaults_to_analyst(client):
    me = client.get("/api/v1/me").json()
    assert me["role"] == "analyst"
    assert "template" not in me["screens"]          # config screen hidden for analyst
    assert "workspace" in me["screens"] and "commentary" in me["screens"]
    assert "config:template" not in me["permissions"]


def test_me_admin_sees_config(client):
    me = client.get("/api/v1/me", headers={"X-Role": "admin"}).json()
    assert me["role"] == "admin"
    assert "template" in me["screens"]
    assert "config:template" in me["permissions"]


def test_reviewer_scope_but_not_template(client):
    me = client.get("/api/v1/me", headers={"X-Role": "reviewer"}).json()
    assert "review" in me["screens"] and "template" not in me["screens"]
    assert "config:scope" in me["permissions"]
    assert "config:template" not in me["permissions"]


def test_template_config_requires_admin(client):
    # Analyst / reviewer are forbidden from the template config data + writes.
    assert client.get("/api/v1/projects/demo/template").status_code == 403
    assert client.get("/api/v1/projects/demo/template", headers={"X-Role": "reviewer"}).status_code == 403
    assert client.get("/api/v1/projects/demo/template", headers={"X-Role": "admin"}).status_code == 200

    tpl = {"template_key": "rbac_t", "name": "T", "statements": []}
    assert client.post("/api/v1/templates", json={"definition": tpl}).status_code == 403
    assert client.post("/api/v1/templates", json={"definition": tpl},
                       headers={"X-Role": "admin"}).status_code == 201


def test_edit_allowed_for_working_roles(client):
    # analyst may edit values (simple flow); the mutation is permitted.
    r = client.patch("/api/v1/projects/demo/line-items/ppe", json={"value": 423180, "formula": ""})
    assert r.status_code == 200
    client.delete("/api/v1/projects/demo/line-items/ppe")
