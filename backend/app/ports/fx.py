"""FX conversion port (deferred).

Currency conversion needs an FX rate source, decided with the infra choice. The
port is defined so the rest of the system can depend on it; it is left unbound.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class FxConverter(Protocol):
    id: str

    def rate(self, base: str, quote: str, on: date) -> Decimal: ...
