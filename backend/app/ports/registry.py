"""Adapter registry — config-driven selection of concrete implementations.

Adapters register by ``id``; the pipeline asks the registry for a provider of a
given kind and gets whichever id configuration selected. Unknown ids raise clearly.
"""
from __future__ import annotations

from typing import Any, Callable


class Registry:
    def __init__(self) -> None:
        self._factories: dict[str, dict[str, Callable[[], Any]]] = {}

    def register(self, kind: str, provider_id: str, factory: Callable[[], Any]) -> None:
        self._factories.setdefault(kind, {})[provider_id] = factory

    def get(self, kind: str, provider_id: str) -> Any:
        try:
            return self._factories[kind][provider_id]()
        except KeyError as exc:
            available = sorted(self._factories.get(kind, {}))
            raise KeyError(
                f"No {kind!r} adapter registered with id {provider_id!r}. "
                f"Available: {available or '[]'}"
            ) from exc

    def available(self, kind: str) -> list[str]:
        return sorted(self._factories.get(kind, {}))


registry = Registry()
