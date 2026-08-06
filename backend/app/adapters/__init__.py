"""Concrete adapter implementations, registered into the global registry.

Importing this package registers all built-in adapters (currently stubs plus the
local object store). Real engines (PaddleOCR, PP-Structure, Anthropic, etc.) are
added here behind their optional-dependency extras without touching the core.
"""
from __future__ import annotations

from app.config import get_settings
from app.ports.object_store import LocalObjectStore
from app.ports.registry import registry

from .stubs import (
    StubEmbeddingProvider,
    StubLlmProvider,
    StubOcrProvider,
    StubTableStructureProvider,
)


def register_builtins() -> None:
    settings = get_settings()

    registry.register("ocr", "stub", StubOcrProvider)
    registry.register("table", "stub", StubTableStructureProvider)
    registry.register("llm", "stub", StubLlmProvider)
    registry.register("embedding", "stub", StubEmbeddingProvider)

    registry.register(
        "object_store", "local",
        lambda: LocalObjectStore(settings.object_store_root),
    )


register_builtins()
