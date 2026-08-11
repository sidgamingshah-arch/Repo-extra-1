"""Application configuration.

Settings are layered, highest precedence first:

  1. Environment variables (prefix ``FINEX_``; nested keys use ``__``, e.g.
     ``FINEX_LLM__MODEL``, ``FINEX_FEATURES__UI_LOCALIZATION``).
  2. ``.env`` file.
  3. ``config.toml`` at the backend root — the human-editable, git-safe config file
     for LLM / OCR / extraction / auth / feature settings (see that file's comments).
  4. Built-in defaults below.

Everything infra-specific (database URL, object store, which OCR/LLM adapters to
use) can therefore be deferred to deployment. Defaults are chosen so the app runs
locally with zero external services (SQLite + local object store + stub engines).

Secrets (API keys, DB passwords) are NEVER read from ``config.toml`` — the LLM key is
read at call time from the environment variable named by ``llm.api_key_env``.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# config.toml lives at the backend root (two levels up from this file: app/config.py).
_CONFIG_TOML = Path(__file__).resolve().parent.parent / "config.toml"


class AuthSettings(BaseModel):
    """Authentication / session behaviour."""

    # Accept the X-Role header as a dev/service credential when there is no session.
    # OFF by default (a real session token is the only way in); enable explicitly for
    # local dev / CI only. A valid session always takes precedence over this header.
    allow_role_header: bool = False
    # Passwordless quick-login for the seeded demo users. Set False in production.
    demo_mode: bool = True
    # Session token lifetime in minutes.
    session_ttl_minutes: int = 480


class FeatureSettings(BaseModel):
    """Admin-configurable feature flags."""

    # Localize the whole UI (not just extracted financial output). Startup default;
    # an admin can flip it at runtime from the Settings screen.
    ui_localization: bool = False
    # Require a second-person reviewer SIGN-OFF on the analyst's output. When False the
    # workflow closes at the analyst (they finalize & export directly). This governs the
    # sign-off/hand-off only — the human-in-the-loop Review Queue (checks + low-confidence
    # QA) stays available to the analyst either way. Admin-flippable at runtime.
    review_required: bool = True
    # Load the seeded sample project at startup. Off by default → the app starts
    # greenfield (empty); an admin can load/clear the sample at runtime from Settings.
    seed_demo: bool = False
    default_output_locale: str = "en"
    supported_locales: list[str] = Field(default_factory=lambda: ["en", "zh", "ar", "fr"])


class LlmSettings(BaseModel):
    """Configuration for the selected LLM adapter (used for mapping disambiguation)."""

    provider: str = "stub"            # anthropic | openai | local | stub
    model: str = "claude-opus-4-8"
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout_seconds: int = 60
    base_url: str = ""                # empty = provider default
    api_key_env: str = "ANTHROPIC_API_KEY"  # env var the key is read from (not the key)


class OcrSettings(BaseModel):
    # docling = recommended free, pip-only engine (layout + OCR + tables, no system binary);
    # azure = Azure AI Document Intelligence (cloud layout+OCR+tables); paddleocr / tesseract
    # are alternatives. Default stays "stub" so the app runs offline with zero external
    # services; set the engine (and provide its config/extra) for scanned docs.
    engine: str = "stub"              # docling | azure | paddleocr | tesseract | stub
    languages: list[str] = Field(default_factory=lambda: ["en"])
    dpi: int = 300

    # Azure AI Document Intelligence (used when engine = "azure"). The resource endpoint
    # and model are config; the key is read at call time from the env var named below, so
    # the secret never lives in config or the UI (same policy as the LLM key).
    azure_endpoint: str = ""                          # e.g. https://<resource>.cognitiveservices.azure.com
    azure_model: str = "prebuilt-layout"              # prebuilt-layout | prebuilt-read
    azure_api_version: str = "2024-11-30"
    azure_api_key_env: str = "AZURE_DI_KEY"


class EmbeddingSettings(BaseModel):
    provider: str = "stub"            # sentence-transformers | openai | stub
    model: str = "paraphrase-multilingual-MiniLM-L12-v2"


class ExtractionSettings(BaseModel):
    """Pipeline tuning: native/scanned detection, the mapping ensemble, reconciliation."""

    # Native-vs-scanned page detection (see stages/ingest.py).
    native_min_chars: int = 100
    native_min_text_coverage: float = 0.02
    low_dpi_threshold: int = 150
    # Mapping ensemble thresholds (see services/mapping.py).
    # Fuzzy scores are coverage-weighted (see services.mapping._fuzzy_score), so this
    # threshold sits on that combined scale — not on a raw rapidfuzz ratio.
    #
    # 0.55 is measured, not guessed. Swept against a real 270-page filing with the template's
    # own subtotals as the oracle: 0.70 → 0.55 changes not one mapping and every rollup keeps
    # tying, while 0.48 breaks three subtotals and 0.40 breaks five — and the extra mappings
    # those buy are all wrong ("Loss on disposal of investment properties" → ADDITIONS to
    # investment properties, "Gain on disposal of subsidiaries" → ACQUISITION of subsidiaries).
    #
    # The reason lowering it cannot help is structural: a caption with no good concept now has a
    # correct home in its section's residual bucket (stages/residual.py). A looser bar does not
    # rescue an unmapped line, it steals a correctly-routed one and asserts something false
    # about it. Mapping those by MEANING is the LLM tier's job, not a string threshold's.
    fuzzy_accept: float = 0.55        # combined fuzzy score to auto-accept, alone
    # …and the caption must also explain this much of the matched alias, so a heading that
    # is merely contained in a longer concept name can never auto-accept.
    fuzzy_min_alias_coverage: float = 0.45
    fuzzy_candidate: float = 0.45     # minimum score to keep as a candidate
    embedding_accept: float = 0.82    # cosine similarity to accept
    mapping_margin: float = 0.08      # winner must beat runner-up by this margin
    # Confidence + reconciliation.
    auto_accept_confidence: float = 0.80
    recon_abs_tolerance: float = 1.0
    recon_rel_tolerance: float = 0.005
    # Mapping strategy. When an LLM provider is configured, mapping is DESCRIPTION-BASED:
    # the model chooses the canonical concept by meaning (using each candidate's
    # description), not string similarity. The lexical/fuzzy tiers only pre-shortlist
    # candidates. Set false to force the deterministic ensemble even with an LLM present.
    llm_mapping: bool = True
    llm_candidate_cap: int = 40   # max candidate concepts shown to the LLM per line
    # Mapping granularity. "per_statement" (default, most accurate) maps all of a
    # statement's lines in ONE LLM call so cross-line judgements — parent/child
    # containment, residualisation, "Others" handling — have full context. "per_line"
    # maps each line independently (cheaper, less context-aware).
    mapping_scope: Literal["per_statement", "per_line"] = "per_statement"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINEX_",
        env_file=".env",
        env_nested_delimiter="__",
        toml_file=str(_CONFIG_TOML),
        extra="ignore",
    )

    app_name: str = "FinExtract Extraction API"
    api_prefix: str = "/api/v1"

    # Persistence — SQLite by default; point at Postgres in prod (portable via SQLAlchemy).
    database_url: str = "sqlite:///./finex.db"

    # Object storage — local filesystem by default (portable via the ObjectStore port).
    object_store_backend: str = "local"  # local | s3 | minio
    object_store_root: Path = Path("./_object_store")

    # Grouped, file-driven configuration (sections in config.toml).
    auth: AuthSettings = AuthSettings()
    features: FeatureSettings = FeatureSettings()
    llm: LlmSettings = LlmSettings()
    ocr: OcrSettings = OcrSettings()
    embeddings: EmbeddingSettings = EmbeddingSettings()
    extraction: ExtractionSettings = ExtractionSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence (first wins): init args > env > .env > config.toml > file secrets.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
