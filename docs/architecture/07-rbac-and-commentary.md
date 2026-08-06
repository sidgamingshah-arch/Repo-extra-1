# RBAC & financial-analysis commentary

## Role-based access control

Three roles with a permission matrix (`backend/app/security/rbac.py`). Configuration is
**admin-controlled**; the analyst gets a deliberately **simple flow**.

| Role | Sees (screens) | Can configure |
|---|---|---|
| **admin** | all 10 screens incl. Template & Ontology and **Settings** | templates, ontology, page scope, export inclusions, documents, **settings** |
| **reviewer** | upload, integrity, scope, workspace, notes, review, commentary, export | page scope only; resolves review items |
| **analyst** | workspace, notes, commentary, export | nothing — view/edit values, run export |

Permissions (e.g. `config:template`, `config:ontology`, `config:scope`, `config:export`,
`config:settings`, `extraction:edit`, `review:resolve`, `export:run`, `commentary:view`)
are granted per role.

**Enforcement** — `require(permission)` is a FastAPI dependency on every config/mutating
endpoint (create template/ontology, edit/revert line item, template config data, export,
settings PATCH, …) returning **403** when the role lacks the permission. The whole
`/projects` router additionally requires an authenticated principal (401 otherwise).
`GET /me` returns the caller's user, role, permissions, and the screens the role may see.

**Identity — session login.** Identity is a **session bearer token** issued by
`POST /auth/login` (see `backend/app/security/session.py` and
[08-configuration-and-auth.md](08-configuration-and-auth.md)). `current_principal`
resolves the caller from `Authorization: Bearer …` (or, only when
`auth.allow_role_header` is enabled, from an `X-Role` dev/service header) and raises
**401** when neither yields a principal. The permission model and its server-side
enforcement are real; swapping the in-memory session store for a real IdP (OIDC/SAML)
does not change the matrix.

**Frontend** — the app renders a **login screen** until a session exists; `GET /me`
drives everything after. The nav rail filters to `me.screens`; routes are guarded
(`RequireScreen` redirects a role away from a screen it can't see); a top-bar user menu
shows the signed-in user and a sign-out button; and admin-only controls
(template/ontology buttons, export "Include" options, page-scope toggles, review resolve
actions, the Settings toggle) are hidden/disabled via `useCan(permission)`. The server
still enforces regardless of the UI.

## Financial-analysis commentary (the Analysis tab)

A one-page, data-driven commentary derived from the *extracted* statements
(`backend/app/services/commentary.py`), exposed at `GET /projects/{id}/commentary`
(permission `commentary:view`; localized via the `locale` param).

- **Ratios** computed from the statement rows: current ratio, debt-to-equity, equity
  ratio, interest coverage, net (pre-tax) margin, YoY revenue growth, cash ratio, asset
  turnover — each tone-coded (good/warn/bad) by threshold.
- **Strengths & risks** are *selected from a fixed, localizable catalog* by threshold
  (e.g. debt-to-equity ≤ 0.5 → "conservatively financed"; open review items →
  "figures provisional pending sign-off"), so the commentary is genuine analysis rather
  than free-form text, and every emitted string is translatable (en/zh/ar/fr).
- **Year-on-year trends** — a period-over-period block (FY25 vs FY24, from the prior-year
  `v2` column) for revenue, pre-tax profit, net margin, operating cash flow, total assets,
  equity, debt-to-equity and interest coverage. Each carries a direction, a delta
  (YoY % for amounts, percentage-points for margins, absolute change for ratios), and a
  favourable/tone flag that understands lower-is-better metrics (a falling debt-to-equity
  is *good*). Trends also feed momentum-based strengths (deleveraging, margin expansion).
- **Headline + assessment** summarise the position; a **data-quality** note surfaces that
  figures are provisional while review items are open. Open review items temper an
  otherwise-strong headline down to "mixed".
- It is an automated analytical summary, **not investment advice** (stated in the UI).

The frontend renders it as a printable one-pager (`frontend/src/screens/Commentary.tsx`):
headline + assessment, a tone-coded metric grid, a **year-on-year trends grid**, and
strengths/risks columns.
