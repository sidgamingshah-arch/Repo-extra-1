"""LLM provider port.

The default implementation should be an Anthropic Claude adapter using structured
tool-use / JSON mode with a Pydantic-validated schema and temperature 0 for
determinism. Verify the exact model id / params against the ``claude-api`` skill at
implementation time. Kept swappable for a self-hosted model (air-gapped).
"""
from __future__ import annotations

from typing import Protocol, Sequence, TypedDict, runtime_checkable

from pydantic import BaseModel


class LlmMessage(TypedDict):
    role: str
    content: str


class LlmMeta(TypedDict, total=False):
    input_tokens: int
    output_tokens: int
    model: str
    confidence: float


@runtime_checkable
class LlmProvider(Protocol):
    id: str

    def complete_structured(
        self,
        *,
        system: str,
        messages: Sequence[LlmMessage],
        response_schema: type[BaseModel],
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> tuple[BaseModel, LlmMeta]: ...
