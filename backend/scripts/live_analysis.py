#!/usr/bin/env python3
"""Live LLM extraction + analysis for one entity — a real Anthropic API call.

Feeds real (uploaded / sample) statement line items to Claude via the project's
``AnthropicLlmProvider`` and asks it to do two things the product's pipeline does:

  1. Map each raw source caption -> a canonical Ind-AS/IFRS key, statement, and sign
     convention (the ontology-mapping step).
  2. Compute standard ratios and a one-page financial-analysis commentary grounded
     ONLY in the supplied figures (the Analysis screen).

It prints the Anthropic ``request_id`` and token usage as proof of a genuine call.

Usage:
    # dry run — prints the exact request that WOULD be sent (no key needed):
    python scripts/live_analysis.py --dry-run

    # live call — requires ANTHROPIC_API_KEY (or the env var named in config.toml):
    export ANTHROPIC_API_KEY=sk-ant-...
    python scripts/live_analysis.py --data scripts/sample_data/infosys_fy24.json

    # point at your own extracted data / a different model:
    python scripts/live_analysis.py --data mydata.json --model claude-opus-4-8
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the backend package importable when run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, Field  # noqa: E402

from app.adapters.anthropic_llm import AnthropicLlmProvider, LlmConfigError  # noqa: E402
from app.config import get_settings  # noqa: E402

DEFAULT_DATA = Path(__file__).resolve().parent / "sample_data" / "infosys_fy24.json"


# ---- Structured response schema the model must return -------------------------
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
    "return on equity, cash + current investments as a share of current liabilities, "
    "and any others that are well-supported) and write a concise one-page analysis "
    "with a headline, strengths and risks.\n"
    "Use ONLY the figures provided — never invent line items or numbers. If a ratio "
    "cannot be computed from the given figures, omit it. Values are in the stated "
    "currency and units."
)


def build_user_message(data: dict) -> str:
    payload = {
        "entity": data.get("entity"),
        "basis": data.get("basis"),
        "standard": data.get("standard"),
        "currency": data.get("currency"),
        "units": data.get("units"),
        "period": data.get("period"),
        "prior_period": data.get("prior_period"),
        "line_items": data.get("line_items", []),
    }
    return (
        "Extract and analyse the following. Column v1 is the current period "
        f"({payload['period']}), v2 the prior period ({payload['prior_period']}).\n\n"
        + json.dumps(payload, indent=2)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Live LLM extraction + analysis for one entity.")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA, help="Path to the input JSON.")
    ap.add_argument("--model", default=None, help="Override the configured model id.")
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--dry-run", action="store_true", help="Print the request without calling the API.")
    args = ap.parse_args()

    data = json.loads(args.data.read_text())
    settings = get_settings()
    if args.model:
        settings.llm.model = args.model  # per-run override

    provider = AnthropicLlmProvider(settings)
    messages = [{"role": "user", "content": build_user_message(data)}]

    if args.dry_run:
        req = provider.build_request(
            system=SYSTEM, messages=messages,
            response_schema=Result, max_tokens=args.max_tokens,
        )
        print("=== DRY RUN — exact request that would be sent ===")
        print(f"model       : {req['model']}")
        print(f"max_tokens  : {req['max_tokens']}")
        print(f"api_key_env : {settings.llm.api_key_env} "
              f"(set this to make the live call)")
        print("\n--- system ---\n" + req["system"])
        print("\n--- messages ---\n" + json.dumps(req["messages"], indent=2))
        return 0

    entity = data.get("entity", "the entity")
    print(f"Calling {settings.llm.model} for a live extraction + analysis of {entity} …\n")
    try:
        result, meta = provider.complete_structured(
            system=SYSTEM, messages=messages,
            response_schema=Result, max_tokens=args.max_tokens,
        )
    except LlmConfigError as exc:
        print(f"ERROR: {exc}\n", file=sys.stderr)
        print("Tip: run with --dry-run to see the exact request without a key.", file=sys.stderr)
        return 2

    print("=== LIVE CALL SUCCEEDED ===")
    print(f"model        : {meta.get('model')}")
    print(f"request_id   : {meta.get('request_id')}")
    print(f"input_tokens : {meta.get('input_tokens')}")
    print(f"output_tokens: {meta.get('output_tokens')}")
    print("\n=== STRUCTURED RESULT ===")
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
