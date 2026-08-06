# FinEx — Financial Statement Extraction Platform

Extracts financial data from documents (Excel, native PDF, scanned PDF/images —
often mixed within one file) into a **predefined, user-editable template**, with a
**confidence score** and **click-to-source provenance** on every number, automated
**checks-and-balances**, a human-in-the-loop **review queue**, and export to
well-formatted **Excel or JSON**.

Analysts today manually re-key financials from the *face* of statements **and** the
*notes*, reconcile them, and verify totals — slow, error-prone, and unauditable.
FinEx automates that while keeping a human in control: every machine value is
editable (with spreadsheet formulas), every edit is audited, and nothing that fails
a balance check slips through silently.

## Status

An **end-to-end integrated product**: a FastAPI backend (extraction pipeline + a
seeded Ind-AS demo project served over real endpoints) and a React/TypeScript
frontend implementing the 8-screen FinExtract design handoff, wired to the backend.
The heavier extraction engines (OCR, LLM) are scaffolded behind swappable adapters
and land in subsequent phases — see [`docs/architecture/`](docs/architecture/).

## Monorepo layout

```
repo-extra-1/
  backend/            FastAPI app + extraction pipeline (Python 3.11+)
  frontend/           React + TypeScript SPA (Vite) — the 8-screen workspace
  docs/architecture/  Design & architecture documents
```

## Quickstart

```bash
# backend  (terminal 1)
cd backend && pip install -e ".[dev]"
pytest -q                                 # backend tests
uvicorn app.main:app --port 8000          # API at http://127.0.0.1:8000  (/docs for OpenAPI)

# frontend (terminal 2)
cd frontend && pnpm install
pnpm dev                                  # app at http://localhost:5173 (proxies /api → backend)
```

Then **sign in**. The app opens on a login screen; in demo mode use the one-click
"Sign in as …" buttons for the seeded users — **admin** (Priya Nair), **reviewer**
(Rahul Mehta), or **analyst** (Ana Ferreira) — or type the username with a matching
password. Non-secret configuration (LLM/OCR/extraction engines, feature flags) lives in
[`backend/config.toml`](backend/config.toml) and is surfaced read-only on the admin
**Settings** screen.

Optional backend engines install behind extras so the core stays light:
`pip install -e ".[ocr]"` (PaddleOCR), `.[llm]` (Anthropic), `.[embeddings]`,
`.[pdf]`, `.[lang]`.

## The screens

Upload → Integrity → Page Scope → **Workspace** (side-by-side source ↔ template, inline
edit + formulas, confidence scores) → Review Queue (balance/subtotal/sign/note-recon
checks) → All Notes (note-to-face reconciliation) → **Analysis** (one-page financial
commentary — ratios, **year-on-year trends**, strengths/risks) → Template & Ontology
(incl. the note-netting rule) → **Settings** (admin) → Export (Excel/JSON).
Upload/integrity/scope use the real pipeline; the other views render the backend's
seeded demo project.

## Access control, config & languages

- **Login / session** — a bearer-token session (`POST /auth/login`) with seeded demo
  users. `GET /me` drives the nav and route guards; sign out from the top bar. Identity
  swaps to a real IdP without changing the permission model.
- **RBAC** — three roles (admin / reviewer / analyst). Configuration (templates,
  ontology, page scope, export inclusions, settings) is admin-controlled; the analyst
  gets a simple flow. Server-side enforced (401/403) and reflected in the nav. See
  [`docs/architecture/07-rbac-and-commentary.md`](docs/architecture/07-rbac-and-commentary.md).
- **Configuration** — `backend/config.toml` (LLM, OCR, embeddings, extraction
  thresholds, auth, feature flags), env-overridable, surfaced on the admin Settings
  screen. See [`docs/architecture/08-configuration-and-auth.md`](docs/architecture/08-configuration-and-auth.md).
- **Multilingual** — English, Chinese, Arabic (RTL) and French. By default the language
  picker localizes **only the extracted financial output and line items**; localizing the
  whole interface is an admin toggle. See
  [`docs/architecture/04-multilingual.md`](docs/architecture/04-multilingual.md).

## Capabilities & where they live

| Capability | Design | Code (this phase) |
|---|---|---|
| Excel / native-PDF / scanned ingest, per-page routing | ✅ | `app/stages/ingest.py` |
| Upfront document-integrity report | ✅ | `app/stages/integrity.py` |
| Locate face / notes pages first | ✅ | `app/stages/classify.py` |
| Ontology-driven multi-strategy mapping (semantic/description/similarity) | ✅ | `app/services/mapping.py` |
| Locale-aware number parsing + sign | ✅ | `app/services/numbers.py` |
| **Note→face subtraction reconciliation** | ✅ | `app/services/reconcile.py` |
| Confidence vector | ✅ | `app/core/models/confidence.py` |
| Template + ontology schemas (frontend-authored, versioned) | ✅ | `app/schemas/` |
| Multilingual parity (en/zh/ar/fr) | ✅ | `app/schemas/languages.py` |
| Consolidated + standalone in one pass | ✅ (model) | `app/core/models/line_item.py` |
| Side-by-side hyperlink provenance (normalized bbox) | ✅ | `app/core/models/geometry.py` |
| OCR / table reconstruction, formulas, export, review queue | ✅ (design) | scaffolded, see roadmap |

Full details in [`docs/architecture/`](docs/architecture/).
