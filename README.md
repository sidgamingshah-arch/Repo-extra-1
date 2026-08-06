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

Optional backend engines install behind extras so the core stays light:
`pip install -e ".[ocr]"` (PaddleOCR), `.[llm]` (Anthropic), `.[embeddings]`,
`.[pdf]`, `.[lang]`.

## The screens

Upload → Integrity → Page Scope → **Workspace** (side-by-side source ↔ template, inline
edit + formulas, confidence scores) → Review Queue (balance/subtotal/sign/note-recon
checks) → All Notes (note-to-face reconciliation) → **Analysis** (one-page financial
commentary — ratios + strengths/risks) → Template & Ontology (incl. the note-netting
rule) → Export (Excel/JSON). Upload/integrity/scope use the real pipeline; the other
views render the backend's seeded demo project.

## Access control & languages

- **RBAC** — three roles (admin / reviewer / analyst). Configuration (templates,
  ontology, page scope, export inclusions) is admin-controlled; the analyst gets a
  simple flow. Server-side enforced (403) and reflected in the nav; switch role from the
  top bar. See [`docs/architecture/07-rbac-and-commentary.md`](docs/architecture/07-rbac-and-commentary.md).
- **Multilingual** — English, Chinese, Arabic (RTL) and French, input = output parity;
  switch language from the top bar. See [`docs/architecture/04-multilingual.md`](docs/architecture/04-multilingual.md).

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
