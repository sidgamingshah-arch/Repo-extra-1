"""Shared helpers for structured (JSON-schema-constrained) LLM adapters.

Both the Anthropic and OpenAI-compatible adapters obtain structured output the same
model-agnostic way: embed the response model's JSON Schema in the system prompt and
validate the returned text with Pydantic. These helpers keep that logic in one place.
"""
from __future__ import annotations

import json

from pydantic import BaseModel


class LlmConfigError(RuntimeError):
    """Raised when an LLM adapter is selected but cannot be used (missing key/SDK)."""


def schema_instruction(response_schema: type[BaseModel]) -> str:
    schema = json.dumps(response_schema.model_json_schema(), indent=2)
    return (
        "Respond with a single JSON object and NOTHING else — no prose, no code "
        "fences, no explanation before or after. The object MUST validate against "
        "this JSON Schema:\n\n" + schema
    )


def strip_fences(text: str) -> str:
    """Tolerate a model that wraps JSON in ```json fences despite instructions."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()
