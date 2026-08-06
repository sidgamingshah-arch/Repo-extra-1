# Scripts

## `live_analysis.py` — real Claude extraction + analysis for one entity

Feeds an entity's line items to Claude through the project's real `AnthropicLlmProvider`
and asks it to (1) map each raw source caption to a canonical Ind-AS/IFRS key + statement
+ sign convention, and (2) compute ratios and a one-page financial-analysis commentary
grounded only in the supplied figures. Prints the Anthropic `request_id` and token usage
as proof of a genuine call.

```bash
cd backend
pip install -e ".[llm]"          # installs the anthropic SDK

# 1) Dry run — prints the exact request that WOULD be sent (no key needed):
python scripts/live_analysis.py --dry-run

# 2) Live call — set the key named in config.toml [llm].api_key_env (default below):
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/live_analysis.py --data scripts/sample_data/infosys_fy24.json

# Point at your own extracted data, or override the model:
python scripts/live_analysis.py --data mydata.json --model claude-opus-4-8
```

The model, timeout and endpoint come from `config.toml` `[llm]`; the API key is read at
call time from the environment (never stored in config). The bundled
`sample_data/infosys_fy24.json` holds **approximate, publicly-reported** figures purely
as a realistic input — in the real pipeline these are replaced by values extracted from
the uploaded filing; verify against the official report before relying on any number.

`--dry-run` and the adapter's parsing/meta handling are covered by
`tests/test_anthropic_llm.py` (no network required).
