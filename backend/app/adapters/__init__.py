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

    # Real Claude adapter — registered under its own id so it's available when
    # llm.provider = "anthropic". The class is imported lazily and constructs its
    # SDK client only on first use, so registering it needs neither the SDK nor a key.
    from .anthropic_llm import AnthropicLlmProvider

    registry.register("llm", "anthropic", AnthropicLlmProvider)

    # OpenAI-compatible adapter (OpenAI, TokenRouter, OpenRouter, vLLM, …) — selected
    # when llm.provider = "openai" / "openai_compatible". Uses httpx at call time; the
    # base_url + model come from config.toml [llm], the key from llm.api_key_env.
    from .openai_llm import OpenAiLlmProvider

    registry.register("llm", "openai", OpenAiLlmProvider)
    registry.register("llm", "openai_compatible", OpenAiLlmProvider)

    # Real OCR adapter (scanned pages) — registered under its id so it's available when
    # ocr.engine = "paddleocr". Lazy: needs the 'ocr' extra + models only on first use.
    from .paddle_ocr import PaddleOcrProvider

    registry.register("ocr", "paddleocr", PaddleOcrProvider)

    registry.register(
        "object_store", "local",
        lambda: LocalObjectStore(settings.object_store_root),
    )


register_builtins()
