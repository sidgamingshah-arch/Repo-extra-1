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

This repository currently contains the **backend foundation** (requirement-driven,
runnable, and tested) plus the full architecture design under
[`docs/architecture/`](docs/architecture/). The React/TypeScript frontend and the
heavier extraction engines (OCR, LLM) are scaffolded behind swappable adapters and
land in subsequent phases — see the roadmap in the docs.

## Monorepo layout

```
repo-extra-1/
  backend/            FastAPI app + extraction pipeline (Python 3.11+)   ← implemented
  frontend/           React + TypeScript SPA                             (planned)
  packages/contract/  Shared JSON schemas + type defs                    (planned)
  docs/architecture/  Design & architecture documents
```

## Quickstart (backend)

```bash
cd backend
pip install -e ".[dev]"          # core + dev deps (no heavy ML)
pytest -q                        # 32 tests, all green
uvicorn app.main:app --reload    # serves http://127.0.0.1:8000  (/docs for OpenAPI)
```

Optional engines install behind extras so the core stays light:
`pip install -e ".[ocr]"` (PaddleOCR), `.[llm]` (Anthropic), `.[embeddings]`,
`.[pdf]`, `.[lang]`.

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
