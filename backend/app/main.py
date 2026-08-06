"""FastAPI application entrypoint.

Wires the routers under the configured API prefix and registers built-in adapters.
Run locally with: ``uvicorn app.main:app --reload`` (from the ``backend`` dir).
"""
from __future__ import annotations

from fastapi import FastAPI

import app.adapters  # noqa: F401 - registers built-in adapters on import
from app.api.routes import (
    documents,
    extractions,
    languages,
    ontologies,
    review,
    templates,
)
from app.config import get_settings
from app.db.base import init_db


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, version="0.1.0")

    @application.on_event("startup")
    def _startup() -> None:  # pragma: no cover - trivial
        init_db()

    @application.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "app": settings.app_name}

    prefix = settings.api_prefix
    application.include_router(documents.router, prefix=prefix)
    application.include_router(extractions.router, prefix=prefix)
    application.include_router(templates.router, prefix=prefix)
    application.include_router(ontologies.router, prefix=prefix)
    application.include_router(languages.router, prefix=prefix)
    application.include_router(review.router, prefix=prefix)
    return application


app = create_app()
