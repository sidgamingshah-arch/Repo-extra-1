# Configuration & authentication

## Configuration file (`backend/config.toml`)

Non-secret, deployment-tunable settings live in `backend/config.toml` and are loaded by
`app/config.py` via pydantic-settings. Layering, highest precedence first:

1. **Environment variables** — prefix `FINEX_`, nested keys use `__`
   (e.g. `FINEX_LLM__MODEL`, `FINEX_FEATURES__UI_LOCALIZATION=true`).
2. **`.env`** file.
3. **`config.toml`** — the human-editable file (checked into git).
4. Built-in defaults in `app/config.py`.

`settings_customise_sources` inserts a `TomlConfigSettingsSource` between dotenv and the
defaults, so env always wins over the file. Settings are grouped into nested models:

| Section | Keys |
|---|---|
| `[auth]` | `allow_role_header`, `demo_mode`, `session_ttl_minutes` |
| `[features]` | `ui_localization`, `default_output_locale`, `supported_locales` |
| `[llm]` | `provider`, `model`, `temperature`, `max_tokens`, `timeout_seconds`, `base_url`, `api_key_env` |
| `[ocr]` | `engine`, `languages`, `dpi` |
| `[embeddings]` | `provider`, `model` |
| `[extraction]` | native/scanned thresholds, the mapping-ensemble thresholds, reconciliation tolerances |

**Secrets are never stored here.** The LLM key is read at call time from the environment
variable named by `llm.api_key_env` (default `ANTHROPIC_API_KEY`); the config only names
the variable. `GET /settings` reports whether that variable is populated
(`key_configured`), never its value.

## Settings API + admin Settings screen

`GET /settings` (any authenticated caller) returns a non-secret snapshot of the config —
so the frontend can surface it and read runtime flags. `PATCH /settings`
(`config:settings`, admin only) flips the runtime-mutable flags; today that is
`ui_localization`. Runtime overrides live in `app/services/settings_state.py` (an
in-memory overlay seeded from the config default — swap for a persistent store in
production).

The admin **Settings** screen (`frontend/src/screens/Settings.tsx`) renders the whole
snapshot — LLM, OCR, embeddings, extraction thresholds and access flags, all read-only —
plus the one editable control: the interface-localization toggle (see
[04-multilingual.md](04-multilingual.md)). Non-admins do not see the screen; the server
enforces the `config:settings` permission regardless.

## Session authentication

`app/security/session.py` provides a self-contained session layer so login/logout works
end-to-end with no external infrastructure:

- **Seeded demo users**, one per role — `admin` (Priya Nair), `reviewer` (Rahul Mehta),
  `analyst` (Ana Ferreira). Password equals the username; in **demo mode** the seeded
  users can log in passwordlessly (the "Sign in as …" quick-login buttons).
- `POST /auth/login` → `{username, password?}` authenticates and returns an opaque
  **bearer token**; the token maps to an in-memory session with a TTL.
- `POST /auth/logout` invalidates the token. `GET /auth/demo-users` lists the seeded
  users (no secrets) for the login screen.
- `current_principal` checks the `Authorization: Bearer …` session **first and treats it
  as authoritative** — a valid session's role can never be overridden by a header. Only
  when there is no valid session does it consider an `X-Role` dev/service header, and even
  then solely when `auth.allow_role_header` is enabled. That flag is **off by default**
  (secure by default: a real session is the only way in); enable it explicitly for local
  dev / CI. It 401s when neither yields a principal. `current_role` derives the role from
  the principal, and `require(permission)` builds on it.

**Production hardening** (documented, out of scope for the demo): keep
`auth.allow_role_header=false` (the default) and set `auth.demo_mode=false`; replace the
in-memory session store with a shared, persistent one (Redis / signed JWT); back the
seeded users with a real user store or an IdP (OIDC/SAML). None of this changes the
permission matrix or the API contract.

## LLM provider selection

`config.toml [llm].provider` chooses the adapter the registry hands out (`app/adapters`):

- **`anthropic`** — Anthropic Messages API via the official SDK (`anthropic_llm.py`).
- **`openai` / `openai_compatible`** — the OpenAI **Chat Completions** wire format
  (`openai_llm.py`, via `httpx`), so any compatible gateway works — OpenAI, TokenRouter,
  OpenRouter, a self-hosted vLLM — with a `vendor/model` id (e.g. `moonshotai/kimi-k3-free`).
  Set `base_url` to the gateway (ending in `/v1`) and point `api_key_env` at the key's env var.
- **`stub` / `local`** — offline / no-op.

Both real adapters get structured output the same model-agnostic way (JSON Schema embedded
in the system prompt, Pydantic-validated — shared in `adapters/_structured.py`) and return
input/output token usage in `LlmMeta` for the audit log. Keys are read from the environment
at call time, never from `config.toml`.

**Editable at runtime.** An admin can change the LLM configuration (provider, model,
base_url, temperature, max_tokens, timeout, and the *name* of the key's env var) live from
the Settings screen — `PATCH /settings {"llm": {…}}`. `settings_state.set_llm_config`
applies the edit onto the process-wide `Settings.llm` so the provider registry and adapters
pick it up immediately (in-memory, per-process; resets on restart). The **API key itself is
never accepted from the UI** — only `api_key_env` is editable; the snapshot reports whether
that env var is currently populated (`key_configured`).

## Frontend flow

`frontend/src/lib/api.ts` sends the stored bearer token on every request and exposes
`login`/`logout`/`demoUsers`/`settings`/`patchSettings`. `App.tsx` shows `Login` until a
valid session exists (a 401 from `/me` returns the user to login); once authenticated it
renders the shell and, via a `useSettings()` sync, mirrors `features.ui_localization` into
the UI store so the interface-localization policy takes effect immediately.
