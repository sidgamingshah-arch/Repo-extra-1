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
- `current_principal` resolves the caller from `Authorization: Bearer …`, or — only when
  `auth.allow_role_header` is on — from an `X-Role` dev/service header, and 401s
  otherwise. `current_role` derives the role from the principal, and `require(permission)`
  builds on it.

**Production hardening** (documented, out of scope for the demo): set
`auth.allow_role_header=false` and `auth.demo_mode=false`; replace the in-memory session
store with a shared, persistent one (Redis / signed JWT); back the seeded users with a
real user store or an IdP (OIDC/SAML). None of this changes the permission matrix or the
API contract.

## Frontend flow

`frontend/src/lib/api.ts` sends the stored bearer token on every request and exposes
`login`/`logout`/`demoUsers`/`settings`/`patchSettings`. `App.tsx` shows `Login` until a
valid session exists (a 401 from `/me` returns the user to login); once authenticated it
renders the shell and, via a `useSettings()` sync, mirrors `features.ui_localization` into
the UI store so the interface-localization policy takes effect immediately.
