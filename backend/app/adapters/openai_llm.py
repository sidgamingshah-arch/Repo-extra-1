"""OpenAI-compatible LLM adapter for the LlmProvider port.

Speaks the OpenAI **Chat Completions** wire format (``POST {base_url}/chat/completions``)
so it works against OpenAI itself and any compatible gateway — TokenRouter, OpenRouter,
Together, a self-hosted vLLM, etc. — and any model they serve (e.g.
``moonshotai/kimi-k3-free``). Selected when ``config.toml [llm].provider`` is ``openai``
(or ``openai_compatible``); the endpoint comes from ``llm.base_url`` and the key is read
at call time from the env var named by ``llm.api_key_env``.

Structured output is obtained the same model-agnostic way as the Anthropic adapter:
embed the response model's JSON Schema in the system prompt and validate with Pydantic.
Uses ``httpx`` (already a dependency) — no vendor SDK required. Token usage is returned
in ``LlmMeta`` (``input_tokens`` / ``output_tokens``) for the audit log.
"""
from __future__ import annotations

import os
from typing import Sequence

import httpx
from pydantic import BaseModel

from app.adapters._structured import LlmConfigError, schema_instruction, strip_fences
from app.config import Settings, get_settings
from app.ports.llm import LlmMessage, LlmMeta

__all__ = ["OpenAiLlmProvider", "LlmConfigError"]


class OpenAiLlmProvider:
    id = "openai"

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()

    def _endpoint(self) -> str:
        base = self._settings.llm.base_url or "https://api.openai.com/v1"
        return base.rstrip("/") + "/chat/completions"

    def _api_key(self) -> str:
        cfg = self._settings.llm
        key = os.environ.get(cfg.api_key_env)
        if not key:
            raise LlmConfigError(
                f"No API key found. Set the {cfg.api_key_env} environment variable "
                f"(configured via config.toml [llm].api_key_env)."
            )
        return key

    def build_body(
        self,
        *,
        system: str,
        messages: Sequence[LlmMessage],
        response_schema: type[BaseModel],
        temperature: float,
        max_tokens: int,
        json_mode: bool = True,
    ) -> dict:
        """Construct the exact request body (used by complete_structured and dry-runs)."""
        full_system = f"{system}\n\n{schema_instruction(response_schema)}"
        body: dict = {
            "model": self._settings.llm.model,
            "messages": [{"role": "system", "content": full_system},
                         *[{"role": m["role"], "content": m["content"]} for m in messages]],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    def complete_structured(
        self,
        *,
        system: str,
        messages: Sequence[LlmMessage],
        response_schema: type[BaseModel],
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> tuple[BaseModel, LlmMeta]:
        headers = {"Authorization": f"Bearer {self._api_key()}", "Content-Type": "application/json"}
        body = self.build_body(
            system=system, messages=messages, response_schema=response_schema,
            temperature=temperature, max_tokens=max_tokens, json_mode=True,
        )
        try:
            with httpx.Client(timeout=self._settings.llm.timeout_seconds) as client:
                resp = client.post(self._endpoint(), headers=headers, json=body)
                # Some gateways reject response_format=json_object; retry once without it.
                if resp.status_code == 400 and "response_format" in resp.text.lower():
                    body = self.build_body(
                        system=system, messages=messages, response_schema=response_schema,
                        temperature=temperature, max_tokens=max_tokens, json_mode=False,
                    )
                    resp = client.post(self._endpoint(), headers=headers, json=body)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LlmConfigError(
                f"Gateway returned {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LlmConfigError(f"Request to {self._endpoint()} failed: {exc}") from exc

        payload = resp.json()
        content = payload["choices"][0]["message"]["content"]
        parsed = response_schema.model_validate_json(strip_fences(content))

        usage = payload.get("usage", {}) or {}
        meta: LlmMeta = {
            "model": payload.get("model", self._settings.llm.model),
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }
        rid = resp.headers.get("x-request-id") or payload.get("id")
        if rid:
            meta["request_id"] = rid  # type: ignore[typeddict-unknown-key]
        return parsed, meta
