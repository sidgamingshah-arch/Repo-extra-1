"""Pipeline stage protocol and context.

A stage is a callable ``run(doc, ctx) -> DocumentModel`` that *enriches* the document
model. Stages collect findings/progress on the context rather than raising for
recoverable problems, so the pipeline can surface all issues and remain re-runnable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from app.config import Settings, get_settings
from app.core.models import DocumentModel
from app.ports.registry import Registry, registry as default_registry


@dataclass
class PipelineContext:
    settings: Settings = field(default_factory=get_settings)
    registry: Registry = field(default_factory=lambda: default_registry)
    object_store: Any = None
    raw_bytes: bytes | None = None            # original uploaded file
    # Explicit extraction scope: INCLUDED page indices (0-based). None = default (all
    # face/notes pages). Set from the document's persisted page_scope so a user's page
    # selection on the Scope screen actually restricts what gets extracted.
    included_pages: set[int] | None = None
    logs: list[str] = field(default_factory=list)
    progress_cb: Callable[[str, float], None] | None = None
    # LLM usage accumulated across stages (description-based mapping, …) for the audit log.
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_calls: int = 0
    llm_model: str = ""
    # How ontology mapping actually ran, and why. A run with no LLM configured silently falls
    # back to the deterministic ensemble, which is materially weaker — recording it means a
    # degraded run is never mistaken for a full-capability one downstream.
    mapping_strategy: str = ""
    mapping_strategy_reason: str = ""

    def log(self, message: str) -> None:
        self.logs.append(message)

    def emit_progress(self, phase: str, pct: float) -> None:
        if self.progress_cb is not None:
            self.progress_cb(phase, pct)


class Stage(Protocol):
    name: str

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel: ...
