"""Embedding provider port.

A multilingual embedding model enables cross-lingual mapping (map a Chinese / Arabic
/ French source label to an English canonical key) — see the multilingual design.
"""
from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    id: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
