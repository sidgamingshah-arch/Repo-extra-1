"""Runtime-mutable settings overlay.

Most settings come from ``config.toml`` / env and change only on redeploy. A few are
meant to be flipped live by an admin from the Settings screen:

  * ``ui_localization``  — localize the whole interface.
  * ``review_required``  — require a reviewer step (else the workflow closes at analyst).
  * the LLM configuration — provider / model / base_url / temperature / max_tokens /
    timeout / api_key_env. Edits are applied onto the process-wide ``Settings.llm`` so
    the provider registry and adapters pick them up immediately. The **API key is never
    stored here** — only the *name* of the env var it is read from.
  * the EXTRACTION thresholds — the mapping ensemble's accept/candidate/margin bars and the
    reconciliation tolerances (see ``EXTRACTION_KNOBS``). Applied onto the process-wide
    ``Settings.extraction``, which the pipeline reads per run, so a change takes effect on the
    next extraction and never rewrites one that already happened.

In-memory means overrides reset on restart and are per-process (documented; a
production build would persist this to the database or a shared store).
"""
from __future__ import annotations

from copy import deepcopy
from typing import NamedTuple

from app.config import get_settings

_RUNTIME: dict = {}
# Snapshot of the config-file LLM defaults, captured once so reset() can restore them.
_LLM_DEFAULTS: dict | None = None
# …and of the extraction defaults, so "restore defaults" means the shipped config values
# rather than whatever the last edit happened to be.
_EXTRACTION_DEFAULTS: dict | None = None

# LLM fields an admin may edit from the UI (the key itself is intentionally excluded).
LLM_EDITABLE = ("provider", "model", "base_url", "temperature", "max_tokens",
                "timeout_seconds", "api_key_env")


class Knob(NamedTuple):
    """One tunable extraction setting, described well enough for a UI to render and validate it
    without knowing anything about mapping.

    The bounds and the guidance live HERE rather than in the frontend, because they are facts
    about the pipeline: a threshold outside its range does not mean anything, and the note on
    each is what stops a well-meaning edit from quietly making mapping worse.
    """

    key: str
    kind: str            # "number" | "bool" | "choice"
    label: str
    help: str
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: tuple[str, ...] = ()


# Every extraction setting an admin may change from the Settings screen. Changing one affects
# FUTURE extractions; it never rewrites a run that already happened.
EXTRACTION_KNOBS: tuple[Knob, ...] = (
    Knob("llm_mapping", "bool", "Map by meaning (LLM)",
         "When an LLM provider is configured, concepts are chosen by MEANING from each "
         "candidate's definition and criteria, and the lexical tiers only shortlist. Turn this "
         "off to force the deterministic ensemble even with a provider available."),
    Knob("mapping_scope", "choice", "Mapping granularity",
         "per_statement decides all of a statement's captions in one call, so cross-line "
         "judgements (parent/child containment, residuals, 'Others') have full context. "
         "per_line is cheaper and less context-aware.",
         choices=("per_statement", "per_line")),
    Knob("fuzzy_accept", "number", "Fuzzy auto-accept",
         "Combined (coverage-weighted) string score at which a fuzzy match may decide a mapping "
         "on its own. Measured floor is 0.55: below that, on a real filing, wrong mappings "
         "appear and section subtotals stop tying — and they buy no extra coverage, because a "
         "caption with no good concept already has a correct home in its section's 'Others'.",
         minimum=0.0, maximum=1.0, step=0.01),
    Knob("fuzzy_min_alias_coverage", "number", "Fuzzy alias coverage floor",
         "How much of the matched concept's alias the caption must actually explain. This is "
         "what stops a short heading ('LIABILITIES') from auto-accepting against a much longer "
         "concept name that merely contains it.",
         minimum=0.0, maximum=1.0, step=0.01),
    Knob("fuzzy_candidate", "number", "Fuzzy shortlist floor",
         "Minimum score to keep a fuzzy match as a CANDIDATE. Candidates are evidence and are "
         "offered to the LLM; lowering this widens what the model gets to choose between "
         "without letting string similarity decide anything by itself.",
         minimum=0.0, maximum=1.0, step=0.01),
    Knob("embedding_accept", "number", "Embedding accept",
         "Cosine similarity at which an embedding match may decide a mapping alone.",
         minimum=0.0, maximum=1.0, step=0.01),
    Knob("mapping_margin", "number", "Winner margin",
         "How far the winning concept must beat the runner-up before the mapping is accepted "
         "without review. A close call is routed to a human instead of guessed.",
         minimum=0.0, maximum=1.0, step=0.01),
    Knob("auto_accept_confidence", "number", "Auto-accept confidence",
         "Combined confidence at or above which a mapped line is accepted without review. "
         "Anything below lands in the review queue as low confidence.",
         minimum=0.0, maximum=1.0, step=0.01),
    Knob("recon_abs_tolerance", "number", "Reconciliation tolerance (absolute)",
         "Absolute floor when comparing a note total to the face figure it supports, in the "
         "document's own units.",
         minimum=0.0, maximum=1e9, step=1.0),
    Knob("recon_rel_tolerance", "number", "Reconciliation tolerance (relative)",
         "Relative band for the same comparison, so large figures are not held to sub-unit "
         "precision.",
         minimum=0.0, maximum=1.0, step=0.001),
    Knob("recon_corroboration_rel", "number", "Note-breakdown corroboration band",
         "How near a note total must come to the face figure before we accept the note really "
         "is a BREAKDOWN of it. Beyond this the note is recorded as 'not a breakdown' rather "
         "than reported as a mismatch — most cited notes are analyses or segment tables. "
         "Raising this turns more near-misses into review items; lowering it reports fewer.",
         minimum=0.0, maximum=1.0, step=0.01),
)

_KNOB_BY_KEY = {k.key: k for k in EXTRACTION_KNOBS}


def _seed() -> None:
    global _LLM_DEFAULTS, _EXTRACTION_DEFAULTS
    feats = get_settings().features
    _RUNTIME.setdefault("ui_localization", feats.ui_localization)
    _RUNTIME.setdefault("review_required", feats.review_required)
    _RUNTIME.setdefault("seed_demo", feats.seed_demo)
    if _LLM_DEFAULTS is None:
        llm = get_settings().llm
        _LLM_DEFAULTS = {k: getattr(llm, k) for k in LLM_EDITABLE}
    if _EXTRACTION_DEFAULTS is None:
        ex = get_settings().extraction
        _EXTRACTION_DEFAULTS = {k.key: getattr(ex, k.key) for k in EXTRACTION_KNOBS}


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


def extraction_config() -> dict:
    """The extraction settings an admin may edit, with the shipped default for each.

    ``defaults`` is what the config file said at startup, so the UI can offer "restore defaults"
    and show at a glance which knobs have been moved away from them.
    """
    _seed()
    ex = get_settings().extraction
    return {
        "values": {k.key: getattr(ex, k.key) for k in EXTRACTION_KNOBS},
        "defaults": dict(_EXTRACTION_DEFAULTS or {}),
        "fields": [
            {"key": k.key, "kind": k.kind, "label": k.label, "help": k.help,
             "min": k.minimum, "max": k.maximum, "step": k.step,
             "choices": list(k.choices)}
            for k in EXTRACTION_KNOBS
        ],
    }


def set_extraction_config(**fields) -> dict:
    """Apply admin edits onto the live extraction settings, refusing anything out of range.

    Only the declared knobs are honoured. A value outside a knob's bounds is REJECTED rather
    than clamped: silently substituting a different threshold than the one an admin typed would
    make the screen lie about what the pipeline is doing.

    Raises ValueError naming the offending field.
    """
    _seed()
    ex = get_settings().extraction
    cleaned: dict = {}
    for key, value in fields.items():
        knob = _KNOB_BY_KEY.get(key)
        if knob is None or value is None:
            continue
        if knob.kind == "bool":
            cleaned[key] = bool(value)
            continue
        if knob.kind == "choice":
            if str(value) not in knob.choices:
                raise ValueError(
                    f"{key} must be one of {', '.join(knob.choices)} (got {value!r})")
            cleaned[key] = str(value)
            continue
        try:
            num = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a number (got {value!r})") from exc
        if knob.minimum is not None and num < knob.minimum:
            raise ValueError(f"{key} must be at least {knob.minimum} (got {num})")
        if knob.maximum is not None and num > knob.maximum:
            raise ValueError(f"{key} must be at most {knob.maximum} (got {num})")
        cleaned[key] = num
    for key, value in cleaned.items():
        setattr(ex, key, value)
    return extraction_config()


def reset_extraction_config() -> dict:
    """Restore every extraction knob to the value the config file shipped."""
    _seed()
    ex = get_settings().extraction
    for key, value in (_EXTRACTION_DEFAULTS or {}).items():
        setattr(ex, key, value)
    return extraction_config()


def reset() -> None:
    """Test helper: drop runtime overrides so config defaults are re-seeded."""
    global _LLM_DEFAULTS, _EXTRACTION_DEFAULTS
    _RUNTIME.clear()
    if _LLM_DEFAULTS is not None:
        llm = get_settings().llm
        for k, v in _LLM_DEFAULTS.items():
            setattr(llm, k, v)
        _LLM_DEFAULTS = None
    if _EXTRACTION_DEFAULTS is not None:
        ex = get_settings().extraction
        for k, v in _EXTRACTION_DEFAULTS.items():
            setattr(ex, k, v)
        _EXTRACTION_DEFAULTS = None
