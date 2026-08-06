"""Runtime-mutable settings overlay.

Most settings come from ``config.toml`` / env and change only on redeploy. A few are
meant to be flipped live by an admin from the Settings screen — currently the
interface-localization feature flag. Those live here as a small in-memory overlay
seeded from the config-file default.

In-memory means the override resets on restart and is per-process (documented; a
production build would persist this to the database or a shared store).
"""
from __future__ import annotations

from app.config import get_settings

_RUNTIME: dict = {}


def _seed() -> None:
    if "ui_localization" not in _RUNTIME:
        _RUNTIME["ui_localization"] = get_settings().features.ui_localization


def get_ui_localization() -> bool:
    _seed()
    return bool(_RUNTIME["ui_localization"])


def set_ui_localization(value: bool) -> bool:
    _RUNTIME["ui_localization"] = bool(value)
    return _RUNTIME["ui_localization"]


def reset() -> None:
    """Test helper: drop runtime overrides so the config default is re-seeded."""
    _RUNTIME.clear()
