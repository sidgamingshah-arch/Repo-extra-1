"""Runtime-mutable settings overlay.

Most settings come from ``config.toml`` / env and change only on redeploy. A few are
meant to be flipped live by an admin from the Settings screen:

  * ``ui_localization``  — localize the whole interface.
  * ``review_required``  — require a reviewer step (else the workflow closes at analyst).
  * the LLM configuration — provider / model / base_url / temperature / max_tokens /
    timeout / api_key_env. Edits are applied onto the process-wide ``Settings.llm`` so
    the provider registry and adapters pick them up immediately. The **API key is never
    stored here** — only the *name* of the env var it is read from.

In-memory means overrides reset on restart and are per-process (documented; a
production build would persist this to the database or a shared store).
"""
from __future__ import annotations

from copy import deepcopy

from app.config import get_settings

_RUNTIME: dict = {}
# Snapshot of the config-file LLM defaults, captured once so reset() can restore them.
_LLM_DEFAULTS: dict | None = None

# LLM fields an admin may edit from the UI (the key itself is intentionally excluded).
LLM_EDITABLE = ("provider", "model", "base_url", "temperature", "max_tokens",
                "timeout_seconds", "api_key_env")


def _seed() -> None:
    global _LLM_DEFAULTS
    feats = get_settings().features
    _RUNTIME.setdefault("ui_localization", feats.ui_localization)
    _RUNTIME.setdefault("review_required", feats.review_required)
    _RUNTIME.setdefault("seed_demo", feats.seed_demo)
    if _LLM_DEFAULTS is None:
        llm = get_settings().llm
        _LLM_DEFAULTS = {k: getattr(llm, k) for k in LLM_EDITABLE}


def get_seed_demo() -> bool:
    """Whether the seeded sample project is currently loaded. Off = greenfield/empty."""
    _seed()
    return bool(_RUNTIME["seed_demo"])


def set_seed_demo(value: bool) -> bool:
    _seed()
    _RUNTIME["seed_demo"] = bool(value)
    return _RUNTIME["seed_demo"]


def get_ui_localization() -> bool:
    _seed()
    return bool(_RUNTIME["ui_localization"])


def set_ui_localization(value: bool) -> bool:
    _seed()
    _RUNTIME["ui_localization"] = bool(value)
    return _RUNTIME["ui_localization"]


def get_review_required() -> bool:
    _seed()
    return bool(_RUNTIME["review_required"])


def set_review_required(value: bool) -> bool:
    _seed()
    _RUNTIME["review_required"] = bool(value)
    return _RUNTIME["review_required"]


def set_llm_config(**fields) -> dict:
    """Apply admin LLM-config edits onto the live Settings.llm (never the API key).

    Only keys in ``LLM_EDITABLE`` are honoured; unknown keys and any ``api_key``/secret
    values are ignored. Returns the resulting editable LLM config.
    """
    _seed()
    llm = get_settings().llm
    for key, value in fields.items():
        if key in LLM_EDITABLE and value is not None:
            setattr(llm, key, value)
    return {k: getattr(llm, k) for k in LLM_EDITABLE}


def reset() -> None:
    """Test helper: drop runtime overrides so config defaults are re-seeded."""
    global _LLM_DEFAULTS
    _RUNTIME.clear()
    if _LLM_DEFAULTS is not None:
        llm = get_settings().llm
        for k, v in _LLM_DEFAULTS.items():
            setattr(llm, k, v)
        _LLM_DEFAULTS = None
