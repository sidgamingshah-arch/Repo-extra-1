# RBAC & financial-analysis commentary

## Role-based access control

Three roles with a permission matrix (`backend/app/security/rbac.py`). Configuration is
**admin-controlled**; the analyst gets a deliberately **simple flow**.

| Role | Sees (screens) | Can configure |
|---|---|---|
| **admin** | all 9 screens incl. Template & Ontology | templates, ontology, page scope, export inclusions, documents |
| **reviewer** | upload, integrity, scope, workspace, notes, review, commentary, export | page scope only; resolves review items |
| **analyst** | workspace, notes, commentary, export | nothing — view/edit values, run export |

Permissions (e.g. `config:template`, `config:ontology`, `config:scope`, `config:export`,
`extraction:edit`, `review:resolve`, `export:run`, `commentary:view`) are granted per role.

**Enforcement** — `require(permission)` is a FastAPI dependency on every config/mutating
endpoint (create template/ontology, edit/revert line item, template config data, export,
…) returning **403** when the role lacks the permission. `GET /me` returns the caller's
role, permissions, and the screens the role may see.

**Identity** — the current role is read from the `X-Role` request header (default
`analyst`), a pragmatic stand-in for real authentication: the permission model and its
server-side enforcement are real; wiring identity to an IdP (OIDC/SAML) is the remaining
integration and does not change the matrix.

**Frontend** — a role switcher in the top bar sets `X-Role`; the nav rail filters to
`GET /me`'s `screens`; routes are guarded (`RequireScreen` redirects a role away from a
screen it can't see); and admin-only controls (template/ontology buttons on Upload, the
export "Include" options, page-scope toggles, review resolve actions) are hidden/disabled
via `useCan(permission)`. The server still enforces regardless of the UI.

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
- **Headline + assessment** summarise the position; a **data-quality** note surfaces that
  figures are provisional while review items are open.
- It is an automated analytical summary, **not investment advice** (stated in the UI).

The frontend renders it as a printable one-pager (`frontend/src/screens/Commentary.tsx`):
headline + assessment, a tone-coded metric grid, and strengths/risks columns.
