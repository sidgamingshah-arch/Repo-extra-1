"""LLM-backed financial analysis — the structured schema, prompt, and runner used by
the ``POST /projects/{id}/analysis`` endpoint.

Feeds the project's extracted line items to the configured LLM provider (Anthropic or
any OpenAI-compatible gateway — see app/adapters) and asks for canonical mappings plus
ratios and a one-page commentary, validated against :class:`Result`. Returns the parsed
result together with the provider's token-usage meta so the run can be written to the
audit log. Mirrors scripts/live_analysis.py, but as an importable service the API uses.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.ports.llm import LlmMeta, LlmProvider
from app.sample.demo import BALANCE_SHEET, CASH_FLOW, DEMO, PROFIT_AND_LOSS

_STMT_HINTS = (
    (PROFIT_AND_LOSS, "profit_and_loss"),
    (BALANCE_SHEET, "balance_sheet"),
    (CASH_FLOW, "cash_flow"),
)


class Mapping(BaseModel):
    source_label: str
    canonical_key: str = Field(description="snake_case canonical template key, e.g. revenue_from_operations")
    statement: str = Field(description="balance_sheet | profit_and_loss | cash_flow")
    sign_convention: str = Field(description="as_reported | expense_negative | contra_negative")
    confidence: float = Field(ge=0, le=1)


class Ratio(BaseModel):
    name: str
    value: float
    unit: str = Field(description="x | % | ratio")
    basis: str = Field(description="the arithmetic used, e.g. 'PAT / revenue * 100'")
    assessment: str = Field(description="good | watch | risk")


class Analysis(BaseModel):
    headline: str
    ratios: list[Ratio]
    revenue_growth_pct: float
    profit_growth_pct: float
    strengths: list[str]
    risks: list[str]
    caveats: str


class Result(BaseModel):
    entity: str
    mappings: list[Mapping]
    analysis: Analysis


SYSTEM = (
    "You are a financial-statement extraction and analysis engine for Ind-AS / IFRS "
    "filings. You are given an entity's raw line-item captions and values for a period "
    "and its prior period. Do two things:\n"
    "1) For every line item, map the raw caption to a canonical snake_case key, its "
    "statement, and its sign convention.\n"
    "2) Compute standard ratios (net margin, revenue growth YoY, current ratio, "
    "return on equity, and any others that are well-supported) and write a concise "
    "one-page analysis with a headline, strengths and risks.\n"
    "Use ONLY the figures provided — never invent line items or numbers. If a ratio "
    "cannot be computed from the given figures, omit it. Values are in the stated "
    "currency and units."
)


def build_demo_payload() -> dict:
    """Assemble the analysis input from the seeded demo project's statements."""
    proj = DEMO["project"]
    line_items = []
    for rows, hint in _STMT_HINTS:
        for r in rows:
            if r.get("kind") == "item" and (r.get("v1") is not None or r.get("v2") is not None):
                line_items.append({
                    "raw_label": r["label"],
                    "statement_hint": hint,
                    "v1": r.get("v1"),
                    "v2": r.get("v2"),
                })
    return {
        "entity": proj["entity"],
        "basis": "consolidated",
        "standard": proj.get("standard", "Ind-AS"),
        "currency": proj.get("currency", "INR"),
        "units": proj.get("units", "crore"),
        "period": "FY2025",
        "prior_period": "FY2024",
        "line_items": line_items,
    }


def build_user_message(data: dict) -> str:
    return (
        "Extract and analyse the following. Column v1 is the current period "
        f"({data.get('period')}), v2 the prior period ({data.get('prior_period')}).\n\n"
        + json.dumps(data, indent=2)
    )


def run_analysis(provider: LlmProvider, data: dict, *, max_tokens: int = 4096) -> tuple[Result, LlmMeta]:
    """Call the provider for a structured analysis; returns (result, token-usage meta)."""
    messages = [{"role": "user", "content": build_user_message(data)}]
    result, meta = provider.complete_structured(
        system=SYSTEM, messages=messages, response_schema=Result, max_tokens=max_tokens,
    )
    return result, meta  # type: ignore[return-value]
