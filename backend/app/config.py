"""Application configuration.

Everything infra-specific (database URL, object-store backend, which OCR/LLM
adapters to use) is resolved here from environment variables so the choice can be
deferred — see ``docs/architecture``. Defaults are chosen so the app runs locally
with zero external services (SQLite + local-filesystem object store + stub engines).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINEX_", env_file=".env", extra="ignore")

    app_name: str = "FinEx Extraction API"
    api_prefix: str = "/api/v1"

    # Persistence — SQLite by default; point at Postgres in prod (portable via SQLAlchemy).
    database_url: str = "sqlite:///./finex.db"

    # Object storage — local filesystem by default (portable via the ObjectStore port).
    object_store_backend: str = "local"  # local | s3 | minio
    object_store_root: Path = Path("./_object_store")

    # Adapter selection (registry ids). Stubs by default so nothing external is required.
    ocr_provider: str = "stub"
    table_provider: str = "stub"
    llm_provider: str = "stub"
    embedding_provider: str = "stub"

    # Extraction tuning.
    native_min_chars: int = 100          # per-page text threshold for native detection
    native_min_text_coverage: float = 0.02
    low_dpi_threshold: int = 150

    # Mapping ensemble thresholds (see services/mapping.py).
    fuzzy_accept: float = 0.90
    fuzzy_candidate: float = 0.60
    embedding_accept: float = 0.82
    mapping_margin: float = 0.08         # winner must beat runner-up by this margin


@lru_cache
def get_settings() -> Settings:
    return Settings()
