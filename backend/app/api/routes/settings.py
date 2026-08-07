"""Application settings — the admin-facing view of configuration.

``GET /settings`` returns a non-secret snapshot (LLM/OCR/embeddings/extraction config,
auth flags, feature flags). Any authenticated user may read it — the frontend needs
the ``ui_localization`` flag to decide whether to localize the interface. ``PATCH
/settings`` lets an admin flip the runtime-mutable flags (currently interface
localization); everything else is set in config.toml / env and shown read-only.

Secrets are never returned: for the LLM key we report only whether the configured
environment variable is populated (``key_configured``), never the key itself.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import get_settings
from app.security import Permission, current_principal, require
from app.services.settings_state import (
    get_review_required,
    get_seed_demo,
    get_ui_localization,
    set_llm_config,
    set_review_required,
    set_seed_demo,
    set_ui_localization,
)

router = APIRouter(tags=["settings"])


def _snapshot() -> dict:
    s = get_settings()
    return {
        "features": {
            "ui_localization": get_ui_localization(),
            "review_required": get_review_required(),
            "seed_demo": get_seed_demo(),
            "default_output_locale": s.features.default_output_locale,
            "supported_locales": s.features.supported_locales,
        },
        "llm": {
            "provider": s.llm.provider,
            "model": s.llm.model,
            "temperature": s.llm.temperature,
            "max_tokens": s.llm.max_tokens,
            "timeout_seconds": s.llm.timeout_seconds,
            "base_url": s.llm.base_url,
            "api_key_env": s.llm.api_key_env,
            "key_configured": bool(os.environ.get(s.llm.api_key_env)),
        },
        "ocr": {"engine": s.ocr.engine, "languages": s.ocr.languages, "dpi": s.ocr.dpi},
        "embeddings": {"provider": s.embeddings.provider, "model": s.embeddings.model},
        "extraction": {
            "fuzzy_accept": s.extraction.fuzzy_accept,
            "fuzzy_candidate": s.extraction.fuzzy_candidate,
            "embedding_accept": s.extraction.embedding_accept,
            "mapping_margin": s.extraction.mapping_margin,
            "auto_accept_confidence": s.extraction.auto_accept_confidence,
            "recon_abs_tolerance": s.extraction.recon_abs_tolerance,
            "recon_rel_tolerance": s.extraction.recon_rel_tolerance,
        },
        "auth": {
            "allow_role_header": s.auth.allow_role_header,
            "demo_mode": s.auth.demo_mode,
            "session_ttl_minutes": s.auth.session_ttl_minutes,
        },
    }


@router.get("/settings", dependencies=[Depends(current_principal)])
def get_settings_snapshot() -> dict:
    return _snapshot()


class LlmConfigPatch(BaseModel):
    # Non-secret LLM configuration. The API key is NEVER accepted here — only the name
    # of the env var it is read from (api_key_env). Any extra fields are ignored.
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: int | None = None
    api_key_env: str | None = None


class SettingsPatch(BaseModel):
    # Runtime-mutable settings; the rest are config.toml / env driven.
    ui_localization: bool | None = None
    review_required: bool | None = None
    seed_demo: bool | None = None  # load (true) / clear (false) the sample project
    llm: LlmConfigPatch | None = None


@router.patch("/settings", dependencies=[Depends(require(Permission.CONFIG_SETTINGS))])
def update_settings(body: SettingsPatch) -> dict:
    if body.ui_localization is not None:
        set_ui_localization(body.ui_localization)
    if body.review_required is not None:
        set_review_required(body.review_required)
    if body.seed_demo is not None:
        set_seed_demo(body.seed_demo)
    if body.llm is not None:
        set_llm_config(**body.llm.model_dump(exclude_none=True))
    return _snapshot()
