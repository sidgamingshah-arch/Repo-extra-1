"""Review-step toggle + editable LLM config (admin runtime settings)."""
from __future__ import annotations


def test_review_toggle_switches_analyst_finalize(client, auth, anon_client):
    """review_required governs the analyst's finalize vs. submit — but never the QA screen."""
    from app.services import settings_state

    try:
        # Default: review required → analyst submits for review, cannot deliver.
        me = anon_client.get("/api/v1/me", headers=auth("analyst")).json()
        assert "review:submit" in me["permissions"]
        assert "export:run" not in me["permissions"]
        assert "review" in me["screens"]  # human-in-the-loop QA available

        # Admin turns the reviewer sign-off OFF.
        r = client.patch("/api/v1/settings", json={"review_required": False})
        assert r.status_code == 200, r.text
        assert r.json()["features"]["review_required"] is False

        # Now the workflow closes at the analyst: they finalize & export directly.
        me2 = anon_client.get("/api/v1/me", headers=auth("analyst")).json()
        assert "export:run" in me2["permissions"]
        assert "review:submit" not in me2["permissions"]
        assert "review" in me2["screens"]  # QA screen STILL there
    finally:
        settings_state.reset()


def test_submit_for_review_requires_review_on(client, auth, anon_client):
    from app.services import settings_state

    try:
        # Review on (default): analyst can submit for review.
        r = anon_client.post("/api/v1/projects/demo/submit-review", headers=auth("analyst"))
        assert r.status_code == 200, r.text
        assert r.json()["entry"]["action"] == "submit_review"

        # Review off: the submit action is no longer available to the analyst.
        client.patch("/api/v1/settings", json={"review_required": False})
        r2 = anon_client.post("/api/v1/projects/demo/submit-review", headers=auth("analyst"))
        assert r2.status_code == 403
    finally:
        settings_state.reset()


def test_admin_edits_llm_config_key_never_accepted(client):
    """Admin edits provider/model/base_url live; the API key is never taken from the UI."""
    from app.config import get_settings
    from app.services import settings_state

    try:
        r = client.patch("/api/v1/settings", json={"llm": {
            "provider": "openai", "model": "moonshotai/kimi-k3-free",
            "base_url": "https://api.tokenrouter.com/v1", "temperature": 0.3,
            "api_key": "sk-should-be-ignored",  # extra field — must be dropped
        }})
        assert r.status_code == 200, r.text
        llm = r.json()["llm"]
        assert llm["provider"] == "openai"
        assert llm["model"] == "moonshotai/kimi-k3-free"
        assert llm["base_url"] == "https://api.tokenrouter.com/v1"
        assert llm["temperature"] == 0.3
        # Applied onto the live settings so the provider registry picks it up.
        assert get_settings().llm.provider == "openai"
        # The key was NOT stored anywhere on the LLM settings.
        assert not hasattr(get_settings().llm, "api_key")
    finally:
        settings_state.reset()


def test_llm_config_edit_requires_admin(auth, anon_client):
    r = anon_client.patch("/api/v1/settings", json={"llm": {"model": "x"}}, headers=auth("analyst"))
    assert r.status_code == 403


_SEED_RUN_ID = "reliance-industries-ltd-20250731-094212"  # a seeded audit entry


def test_greenfield_empty_until_sample_loaded(client, auth, anon_client):
    """Default is greenfield: the project reports loaded=false and screens get empty data.
    An admin loading the sample repopulates everything."""
    from app.services import settings_state

    try:
        settings_state.set_seed_demo(False)
        hdr = auth("admin")
        proj = anon_client.get("/api/v1/projects/demo", headers=hdr).json()
        assert proj["loaded"] is False
        assert proj["project"]["title"] == "No project yet" and proj["documents"] == []
        assert anon_client.get("/api/v1/projects/demo/statements/balance_sheet", headers=hdr).json()["rows"] == []
        assert anon_client.get("/api/v1/projects/demo/notes", headers=hdr).json()["notes"] == []
        green_audit = anon_client.get("/api/v1/projects/demo/audit", headers=hdr).json()["entries"]
        assert all(e["run_id"] != _SEED_RUN_ID for e in green_audit)  # no seeded rows

        # Admin loads the sample project at runtime.
        r = client.patch("/api/v1/settings", json={"seed_demo": True})
        assert r.status_code == 200 and r.json()["features"]["seed_demo"] is True
        proj2 = anon_client.get("/api/v1/projects/demo", headers=hdr).json()
        assert proj2["loaded"] is True and proj2["project"]["title"]
        assert len(anon_client.get("/api/v1/projects/demo/statements/balance_sheet", headers=hdr).json()["rows"]) > 0
        loaded_audit = anon_client.get("/api/v1/projects/demo/audit", headers=hdr).json()["entries"]
        assert any(e["run_id"] == _SEED_RUN_ID for e in loaded_audit)
    finally:
        settings_state.set_seed_demo(True)
